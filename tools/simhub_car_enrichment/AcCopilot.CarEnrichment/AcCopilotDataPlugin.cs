using GameReaderCommon;
using SimHub.Plugins;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

namespace AcCopilot.CarEnrichment
{
    [PluginDescription("Publishes AC Copilot's authoritative car enrichment to SimHub.")]
    [PluginAuthor("AC Copilot Trainer")]
    [PluginName("AC Copilot car enrichment")]
    public sealed class AcCopilotDataPlugin : IPlugin, IDataPlugin
    {
        private const string UnknownClass = "unknown";
        private const int TrainerFreshMilliseconds = 3500;
        private const int MaximumFrameBytes = 65536;

        private readonly JavaScriptSerializer serializer = new JavaScriptSerializer();
        private CancellationTokenSource cancellation;
        private Task worker;
        private int lifecycleGeneration;
        private string carClass = UnknownClass;
        private string carId = "";
        private string classSource = "";
        private int registryVersion;
        private long lastConnectionTimestamp;
        private int awaitingFreshSessionReplay;
        private volatile bool sidecarConnected;

        public PluginManager PluginManager { get; set; }

        public void Init(PluginManager pluginManager)
        {
            this.AttachDelegate("CarClass", () => CurrentCarClass());
            this.AttachDelegate("CarId", () => CurrentCarId());
            this.AttachDelegate("ClassSource", () => CurrentClassSource());
            this.AttachDelegate("RegistryVersion", () => CurrentRegistryVersion());
            this.AttachDelegate("SidecarConnected", () => sidecarConnected);
            this.AttachDelegate("TrainerConnected", () => TrainerIsFresh());

            int generation = Interlocked.Increment(ref lifecycleGeneration);
            CancellationTokenSource source = new CancellationTokenSource();
            cancellation = source;
            worker = Task.Run(() => RunAsync(source.Token, generation));
            SimHub.Logging.Current.Info("AC Copilot car enrichment bridge started");
        }

        public void DataUpdate(PluginManager pluginManager, ref GameData data)
        {
            // Network work stays entirely off SimHub's game-data critical path.
        }

        public void End(PluginManager pluginManager)
        {
            Interlocked.Increment(ref lifecycleGeneration);
            CancellationTokenSource source = cancellation;
            Task runningWorker = worker;
            cancellation = null;
            worker = null;
            if (source != null)
            {
                source.Cancel();
            }
            bool workerStopped = runningWorker == null;
            if (runningWorker != null)
            {
                try
                {
                    workerStopped = runningWorker.Wait(TimeSpan.FromSeconds(2));
                }
                catch (AggregateException)
                {
                    // Cancellation and socket teardown are expected during SimHub exit.
                    workerStopped = true;
                }
            }
            ClearConnection();
            if (source != null)
            {
                if (workerStopped)
                {
                    source.Dispose();
                }
                else
                {
                    runningWorker.ContinueWith(
                        _ => source.Dispose(),
                        CancellationToken.None,
                        TaskContinuationOptions.ExecuteSynchronously,
                        TaskScheduler.Default);
                }
            }
            SimHub.Logging.Current.Info("AC Copilot car enrichment bridge stopped");
        }

        private async Task RunAsync(CancellationToken token, int generation)
        {
            int retryMilliseconds = 500;
            while (!token.IsCancellationRequested && IsCurrentGeneration(generation))
            {
                try
                {
                    await ConnectAndConsumeAsync(
                        token,
                        generation,
                        () => retryMilliseconds = 500).ConfigureAwait(false);
                    retryMilliseconds = 500;
                }
                catch (OperationCanceledException) when (token.IsCancellationRequested)
                {
                    return;
                }
                catch (Exception error)
                {
                    SimHub.Logging.Current.Warn(
                        "AC Copilot car enrichment sidecar connection failed: " + error.Message);
                }
                finally
                {
                    ClearConnection(generation);
                }

                if (!IsCurrentGeneration(generation))
                {
                    return;
                }
                try
                {
                    await Task.Delay(retryMilliseconds, token).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    return;
                }
                retryMilliseconds = Math.Min(retryMilliseconds * 2, 5000);
            }
        }

        private async Task ConnectAndConsumeAsync(
            CancellationToken token,
            int generation,
            Action onConnected)
        {
            using (ClientWebSocket socket = new ClientWebSocket())
            {
                string authToken = Environment.GetEnvironmentVariable("AC_COPILOT_SIDECAR_TOKEN");
                if (!String.IsNullOrWhiteSpace(authToken))
                {
                    socket.Options.SetRequestHeader("X-AC-Copilot-Token", authToken);
                }

                await socket.ConnectAsync(SidecarUri(), token).ConfigureAwait(false);
                await SendAsync(
                    socket,
                    "{\"v\":1,\"type\":\"hello\",\"client\":\"simhub-car-enrichment\","
                        + "\"client_class\":\"external\"}",
                    token).ConfigureAwait(false);

                string hello = await ReceiveTextAsync(socket, token).ConfigureAwait(false);
                if (!IsHelloAck(hello))
                {
                    throw new InvalidDataException("sidecar did not return hello_ack");
                }
                if (token.IsCancellationRequested || !IsCurrentGeneration(generation))
                {
                    return;
                }
                onConnected();
                sidecarConnected = true;
                await SendAsync(
                    socket,
                    "{\"v\":1,\"type\":\"state.subscribe\","
                        + "\"topics\":[\"connection\",\"session\"]}",
                    token).ConfigureAwait(false);

                while (!token.IsCancellationRequested
                    && IsCurrentGeneration(generation)
                    && socket.State == WebSocketState.Open)
                {
                    string message = await ReceiveTextAsync(socket, token).ConfigureAwait(false);
                    if (message == null)
                    {
                        break;
                    }
                    bool requestSessionReplay = ApplySnapshot(message, generation);
                    if (requestSessionReplay)
                    {
                        await SendAsync(
                            socket,
                            "{\"v\":1,\"type\":\"state.subscribe\","
                                + "\"topics\":[\"session\"]}",
                            token).ConfigureAwait(false);
                    }
                }
            }
        }

        private Uri SidecarUri()
        {
            Dictionary<string, object> settings = ReadLauncherSettings();
            int port;
            string configured = Environment.GetEnvironmentVariable("AC_COPILOT_SIDECAR_PORT");
            if (String.IsNullOrWhiteSpace(configured))
            {
                configured = Convert.ToString(Value(settings, "sidecar_port"));
            }
            if (!Int32.TryParse(configured, out port) || port < 1 || port > 65535)
            {
                port = 8765;
            }
            string host = Environment.GetEnvironmentVariable(
                "AC_COPILOT_SIDECAR_EXTERNAL_BIND");
            if (String.IsNullOrWhiteSpace(host))
            {
                host = Value(settings, "external_bind") as string;
            }
            if (String.IsNullOrWhiteSpace(host)
                || String.Equals(host, "0.0.0.0", StringComparison.Ordinal)
                || String.Equals(host, "::", StringComparison.Ordinal))
            {
                host = "127.0.0.1";
            }
            UriBuilder builder = new UriBuilder("ws", host, port, "/");
            return builder.Uri;
        }

        private Dictionary<string, object> ReadLauncherSettings()
        {
            try
            {
                string gamePointDirectory = Environment.GetEnvironmentVariable(
                    "AC_COPILOT_GAME_POINT_DIR");
                if (String.IsNullOrWhiteSpace(gamePointDirectory))
                {
                    string localAppData = Environment.GetEnvironmentVariable("LOCALAPPDATA");
                    if (String.IsNullOrWhiteSpace(localAppData))
                    {
                        return null;
                    }
                    gamePointDirectory = Path.Combine(
                        localAppData,
                        "AC Copilot Trainer",
                        "GamePoint");
                }
                string path = Path.Combine(gamePointDirectory, "settings.json");
                return serializer.DeserializeObject(File.ReadAllText(path))
                    as Dictionary<string, object>;
            }
            catch (IOException)
            {
                return null;
            }
            catch (UnauthorizedAccessException)
            {
                return null;
            }
            catch (ArgumentException)
            {
                return null;
            }
            catch (InvalidOperationException)
            {
                return null;
            }
        }

        private async Task SendAsync(
            ClientWebSocket socket,
            string message,
            CancellationToken token)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(message);
            await socket.SendAsync(
                new ArraySegment<byte>(bytes),
                WebSocketMessageType.Text,
                true,
                token).ConfigureAwait(false);
        }

        private static async Task<string> ReceiveTextAsync(
            ClientWebSocket socket,
            CancellationToken token)
        {
            byte[] buffer = new byte[4096];
            using (MemoryStream frame = new MemoryStream())
            {
                while (true)
                {
                    WebSocketReceiveResult result = await socket.ReceiveAsync(
                        new ArraySegment<byte>(buffer),
                        token).ConfigureAwait(false);
                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        return null;
                    }
                    if (result.MessageType != WebSocketMessageType.Text)
                    {
                        throw new InvalidDataException("sidecar returned a non-text frame");
                    }
                    frame.Write(buffer, 0, result.Count);
                    if (frame.Length > MaximumFrameBytes)
                    {
                        throw new InvalidDataException("sidecar frame exceeds 64 KiB");
                    }
                    if (result.EndOfMessage)
                    {
                        return Encoding.UTF8.GetString(frame.ToArray());
                    }
                }
            }
        }

        private bool IsHelloAck(string message)
        {
            Dictionary<string, object> frame = ParseObject(message);
            return frame != null
                && Convert.ToInt32(Value(frame, "v") ?? 0) == 1
                && String.Equals(Value(frame, "type") as string, "hello_ack",
                    StringComparison.Ordinal);
        }

        private bool ApplySnapshot(string message, int generation)
        {
            if (!IsCurrentGeneration(generation))
            {
                return false;
            }
            Dictionary<string, object> frame = ParseObject(message);
            if (frame == null
                || !String.Equals(Value(frame, "type") as string, "state.snapshot",
                    StringComparison.Ordinal))
            {
                return false;
            }
            Dictionary<string, object> payload = Value(frame, "payload") as Dictionary<string, object>;
            if (payload == null)
            {
                return false;
            }

            string topic = Value(frame, "topic") as string;
            if (String.Equals(topic, "connection", StringComparison.Ordinal))
            {
                bool wasFresh = TrainerIsFresh();
                double replayAgeMilliseconds = Math.Min(
                    Math.Max(ToDouble(Value(frame, "snapshot_age_ms")), 0),
                    TrainerFreshMilliseconds + 1);
                long replayAgeTicks = (long)(
                    replayAgeMilliseconds * Stopwatch.Frequency / 1000.0);
                Interlocked.Exchange(
                    ref lastConnectionTimestamp,
                    Stopwatch.GetTimestamp() - replayAgeTicks);
                bool isFresh = TrainerIsFresh();
                if (!wasFresh || !isFresh)
                {
                    // A heartbeat gap starts a new identity epoch. Do not allow a
                    // resumed connection frame to resurrect the previous car before
                    // a fresh session snapshot arrives.
                    ClearIdentity();
                }
                if (!wasFresh && isFresh)
                {
                    // Session is event-driven. Ask Lua to replay it whenever a fresh
                    // heartbeat starts or resumes an epoch; the sidecar can otherwise
                    // replay its old cached session before Lua confirms current state.
                    Interlocked.Exchange(ref awaitingFreshSessionReplay, 1);
                    return true;
                }
                return false;
            }
            if (!String.Equals(topic, "session", StringComparison.Ordinal))
            {
                return false;
            }
            if (Interlocked.CompareExchange(ref awaitingFreshSessionReplay, 0, 0) != 0
                && ToDouble(Value(frame, "snapshot_age_ms")) > TrainerFreshMilliseconds)
            {
                // The sidecar immediately replays its cache on subscribe. During
                // recovery, ignore that old identity and wait for Lua's fresh replay.
                return false;
            }

            string resolvedClass = Value(payload, "car_class") as string;
            string resolvedCarId = Value(payload, "car_id") as string;
            string resolvedSource = Value(payload, "car_class_source") as string;
            int resolvedVersion = ToInt32(Value(payload, "car_class_registry_version"));
            Interlocked.Exchange(
                ref carClass,
                String.IsNullOrWhiteSpace(resolvedClass) ? UnknownClass : resolvedClass);
            Interlocked.Exchange(ref carId, resolvedCarId ?? "");
            Interlocked.Exchange(ref classSource, resolvedSource ?? "");
            Interlocked.Exchange(ref registryVersion, resolvedVersion);
            Interlocked.Exchange(ref awaitingFreshSessionReplay, 0);
            return false;
        }

        private Dictionary<string, object> ParseObject(string message)
        {
            if (String.IsNullOrWhiteSpace(message))
            {
                return null;
            }
            try
            {
                return serializer.DeserializeObject(message) as Dictionary<string, object>;
            }
            catch (ArgumentException)
            {
                return null;
            }
            catch (InvalidOperationException)
            {
                return null;
            }
        }

        private static object Value(Dictionary<string, object> source, string key)
        {
            object value;
            return source != null && source.TryGetValue(key, out value) ? value : null;
        }

        private static int ToInt32(object value)
        {
            try
            {
                return value == null ? 0 : Convert.ToInt32(value);
            }
            catch (FormatException)
            {
                return 0;
            }
            catch (OverflowException)
            {
                return 0;
            }
        }

        private static double ToDouble(object value)
        {
            try
            {
                return value == null ? 0 : Convert.ToDouble(value);
            }
            catch (FormatException)
            {
                return 0;
            }
            catch (OverflowException)
            {
                return 0;
            }
        }

        private bool TrainerIsFresh()
        {
            long observed = Interlocked.Read(ref lastConnectionTimestamp);
            double elapsedMilliseconds =
                (Stopwatch.GetTimestamp() - observed) * 1000.0 / Stopwatch.Frequency;
            return sidecarConnected
                && observed > 0
                && elapsedMilliseconds >= 0
                && elapsedMilliseconds <= TrainerFreshMilliseconds;
        }

        private bool IsCurrentGeneration(int generation)
        {
            return Volatile.Read(ref lifecycleGeneration) == generation;
        }

        private string CurrentCarClass()
        {
            return TrainerIsFresh() ? Interlocked.CompareExchange(ref carClass, null, null) : UnknownClass;
        }

        private string CurrentCarId()
        {
            return TrainerIsFresh() ? Interlocked.CompareExchange(ref carId, null, null) : "";
        }

        private string CurrentClassSource()
        {
            return TrainerIsFresh() ? Interlocked.CompareExchange(ref classSource, null, null) : "";
        }

        private int CurrentRegistryVersion()
        {
            return TrainerIsFresh() ? Interlocked.CompareExchange(ref registryVersion, 0, 0) : 0;
        }

        private void ClearIdentity()
        {
            Interlocked.Exchange(ref carClass, UnknownClass);
            Interlocked.Exchange(ref carId, "");
            Interlocked.Exchange(ref classSource, "");
            Interlocked.Exchange(ref registryVersion, 0);
        }

        private void ClearConnection()
        {
            sidecarConnected = false;
            Interlocked.Exchange(ref lastConnectionTimestamp, 0);
            Interlocked.Exchange(ref awaitingFreshSessionReplay, 0);
            ClearIdentity();
        }

        private void ClearConnection(int generation)
        {
            if (IsCurrentGeneration(generation))
            {
                ClearConnection();
            }
        }
    }
}
