# SCons pre-build hook — dump the env['ENV'] that will be used for compile subprocesses.
# Wired in via platformio.ini: extra_scripts = pre:tools/scons_env_dump.py
Import("env")
import os

project_dir = env['PROJECT_DIR']
out = os.path.join(project_dir, '_log_scons_env.txt')

with open(out, 'w', encoding='utf-8') as f:
    f.write("=== scons_env_dump ===\n")
    f.write(f"PROJECT_DIR: {project_dir}\n")
    f.write("\n--- os.environ PATH ---\n")
    f.write(os.environ.get('PATH','') + "\n")
    scons_env = env['ENV']
    f.write("\n--- env['ENV'] keys ---\n")
    f.write(str(sorted(scons_env.keys())) + "\n")
    f.write("\n--- env['ENV']['PATH'] ---\n")
    f.write(scons_env.get('PATH','MISSING') + "\n")
    ep = scons_env.get('PATH', '')
    found = []
    for p in ep.split(os.pathsep):
        cand = os.path.join(p, 'xtensa-esp32s3-elf-gcc.exe')
        if os.path.isfile(cand):
            found.append(cand)
    f.write("\n--- xtensa-esp32s3-elf-gcc matches in ENV PATH ---\n")
    f.write(str(found) + "\n")
    try:
        f.write("\n--- CC ---\n" + str(env.get('CC','')) + "\n")
        f.write("\n--- CXX ---\n" + str(env.get('CXX','')) + "\n")
    except Exception as e:
        f.write(f"\nerror dumping env keys: {e}\n")
    f.write("\n=== DONE ===\n")

print(f"[scons_env_dump] wrote {out}")
