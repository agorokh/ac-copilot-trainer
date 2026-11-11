// UTF-8 -> printable ASCII (0x20..0x7E) display folding — issue #86.

#include "ui/ascii_fold.h"

#include <stdint.h>

namespace {

void emit_str(char* dst, size_t dst_n, size_t* out, const char* s) {
    while (*s && *out + 1 < dst_n) {
        dst[(*out)++] = *s++;
    }
}

void emit_char(char* dst, size_t dst_n, size_t* out, char c) {
    if (*out + 1 < dst_n) {
        dst[(*out)++] = c;
    }
}

bool is_cont(uint8_t b) {
    return (b & 0xC0u) == 0x80u;
}

const char* fold_codepoint(uint32_t cp, char single[2]) {
    if (cp >= 0x20u && cp <= 0x7Eu) {
        single[0] = static_cast<char>(cp);
        single[1] = '\0';
        return single;
    }
    // Control characters and combining diacritical marks: drop silently.
    if (cp < 0x20u || (cp >= 0x7Fu && cp <= 0x9Fu) ||
        (cp >= 0x0300u && cp <= 0x036Fu)) {
        return "";
    }
    // Whitespace variants (NBSP, figure/thin/narrow spaces).
    if (cp == 0x00A0u || (cp >= 0x2000u && cp <= 0x200Au) || cp == 0x202Fu) {
        return " ";
    }
    // Apostrophes / single quotes / acute accent.
    if (cp == 0x2018u || cp == 0x2019u || cp == 0x201Au || cp == 0x201Bu ||
        cp == 0x02BCu || cp == 0x00B4u || cp == 0x2032u) {
        return "'";
    }
    // Double quotes / guillemets.
    if (cp == 0x201Cu || cp == 0x201Du || cp == 0x201Eu || cp == 0x201Fu ||
        cp == 0x00ABu || cp == 0x00BBu || cp == 0x2033u) {
        return "\"";
    }
    // Hyphens, en/em dashes, minus, middle dot / bullet separators.
    if ((cp >= 0x2010u && cp <= 0x2015u) || cp == 0x2212u ||
        cp == 0x00B7u || cp == 0x2022u) {
        return "-";
    }
    if (cp == 0x2026u) return "...";
    if (cp == 0x00B0u) return "deg";

    // Latin-1 Supplement (U+00C0..U+00FF).
    if (cp >= 0x00C0u && cp <= 0x00C5u) return "A";
    if (cp == 0x00C6u) return "AE";
    if (cp == 0x00C7u) return "C";
    if (cp >= 0x00C8u && cp <= 0x00CBu) return "E";
    if (cp >= 0x00CCu && cp <= 0x00CFu) return "I";
    if (cp == 0x00D0u) return "D";
    if (cp == 0x00D1u) return "N";
    if ((cp >= 0x00D2u && cp <= 0x00D6u) || cp == 0x00D8u) return "O";
    if (cp == 0x00D7u) return "x";
    if (cp >= 0x00D9u && cp <= 0x00DCu) return "U";
    if (cp == 0x00DDu) return "Y";
    if (cp == 0x00DFu) return "ss";
    if (cp >= 0x00E0u && cp <= 0x00E5u) return "a";
    if (cp == 0x00E6u) return "ae";
    if (cp == 0x00E7u) return "c";
    if (cp >= 0x00E8u && cp <= 0x00EBu) return "e";
    if (cp >= 0x00ECu && cp <= 0x00EFu) return "i";
    if (cp == 0x00F0u) return "d";
    if (cp == 0x00F1u) return "n";
    if ((cp >= 0x00F2u && cp <= 0x00F6u) || cp == 0x00F8u) return "o";
    if (cp >= 0x00F9u && cp <= 0x00FCu) return "u";
    if (cp == 0x00FDu || cp == 0x00FFu) return "y";

    // Common Latin Extended-A motorsport/author letters (U+0100..U+017F).
    switch (cp) {
        case 0x0100u: case 0x0102u: case 0x0104u: return "A";
        case 0x0101u: case 0x0103u: case 0x0105u: return "a";
        case 0x0106u: case 0x0108u: case 0x010Cu: return "C";
        case 0x0107u: case 0x0109u: case 0x010Du: return "c";
        case 0x010Eu: case 0x0110u: return "D";
        case 0x010Fu: case 0x0111u: return "d";
        case 0x0112u: case 0x0116u: case 0x0118u: case 0x011Au: return "E";
        case 0x0113u: case 0x0117u: case 0x0119u: case 0x011Bu: return "e";
        case 0x011Eu: return "G";
        case 0x011Fu: return "g";
        case 0x0130u: return "I";
        case 0x0131u: return "i";
        case 0x0141u: return "L";
        case 0x0142u: return "l";
        case 0x0143u: case 0x0147u: return "N";
        case 0x0144u: case 0x0148u: return "n";
        case 0x0150u: return "O";
        case 0x0151u: return "o";
        case 0x0152u: return "OE";
        case 0x0153u: return "oe";
        case 0x0158u: return "R";
        case 0x0159u: return "r";
        case 0x015Au: case 0x015Eu: case 0x0160u: return "S";
        case 0x015Bu: case 0x015Fu: case 0x0161u: return "s";
        case 0x0162u: case 0x0164u: return "T";
        case 0x0163u: case 0x0165u: return "t";
        case 0x016Eu: case 0x0170u: return "U";
        case 0x016Fu: case 0x0171u: return "u";
        case 0x0178u: return "Y";
        case 0x0179u: case 0x017Bu: case 0x017Du: return "Z";
        case 0x017Au: case 0x017Cu: case 0x017Eu: return "z";
        default: return "?";
    }
}

}  // namespace

extern "C" void ui_ascii_fold(char* dst, size_t dst_n, const char* src) {
    if (!dst || dst_n == 0) return;
    if (!src) {
        dst[0] = '\0';
        return;
    }
    size_t out = 0;
    const auto* p = reinterpret_cast<const uint8_t*>(src);
    char single[2];
    while (*p && out + 1 < dst_n) {
        const uint8_t b0 = p[0];
        if (b0 < 0x80u) {
            if (b0 >= 0x20u && b0 <= 0x7Eu) {
                dst[out++] = static_cast<char>(b0);
            }
            ++p;
            continue;
        }
        uint32_t cp = 0;
        size_t adv = 0;
        if (b0 >= 0xC2u && b0 <= 0xDFu && is_cont(p[1])) {
            cp = (static_cast<uint32_t>(b0 & 0x1Fu) << 6) |
                 static_cast<uint32_t>(p[1] & 0x3Fu);
            adv = 2;
        } else if (b0 >= 0xE0u && b0 <= 0xEFu && is_cont(p[1]) && is_cont(p[2]) &&
                   !(b0 == 0xE0u && p[1] < 0xA0u) &&
                   !(b0 == 0xEDu && p[1] >= 0xA0u)) {
            cp = (static_cast<uint32_t>(b0 & 0x0Fu) << 12) |
                 (static_cast<uint32_t>(p[1] & 0x3Fu) << 6) |
                 static_cast<uint32_t>(p[2] & 0x3Fu);
            adv = 3;
        } else if (b0 >= 0xF0u && b0 <= 0xF4u && is_cont(p[1]) && is_cont(p[2]) &&
                   is_cont(p[3]) &&
                   !(b0 == 0xF0u && p[1] < 0x90u) &&
                   !(b0 == 0xF4u && p[1] >= 0x90u)) {
            cp = (static_cast<uint32_t>(b0 & 0x07u) << 18) |
                 (static_cast<uint32_t>(p[1] & 0x3Fu) << 12) |
                 (static_cast<uint32_t>(p[2] & 0x3Fu) << 6) |
                 static_cast<uint32_t>(p[3] & 0x3Fu);
            adv = 4;
        }
        if (adv == 0) {
            emit_char(dst, dst_n, &out, '?');
            ++p;
            continue;
        }
        emit_str(dst, dst_n, &out, fold_codepoint(cp, single));
        p += adv;
    }
    dst[out] = '\0';
}
