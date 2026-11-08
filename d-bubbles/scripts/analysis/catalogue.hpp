#pragma once

#include "dominators/d_bubbles.hpp"
#include <algorithm>
#include <charconv>
#include <cstdint>
#include <fstream>
#include <limits>
#include <map>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

// Read the bubbles reported by vg.
namespace paper_compare {
constexpr uint32_t NONE = std::numeric_limits<uint32_t>::max();

inline void require(bool ok, const char* why)
{
    if (!ok)
        throw dominators::InvalidInput(std::string("bubble comparison: ") + why);
}

struct Bubble
{
    uint32_t component = NONE, x = NONE, y = NONE;
};

struct Catalogue
{
    // Separate shared bubbles from bubbles found only by vg.
    std::vector<Bubble> extra;
    std::vector<uint64_t> reciprocalEntryBits;
    std::map<std::string, std::string> suppliedProvenance;
    uint64_t rows = 0, commonD = 0;

    bool common(uint32_t inward) const
    {
        require(inward / 64 < reciprocalEntryBits.size(),
                "node side is outside the shared bubble list");
        return (reciprocalEntryBits[inward / 64] >> (inward % 64)) & 1u;
    }
};

// Match nodes by their original names.
class NameIndex
{
    const std::vector<std::string>& names;
    std::vector<uint32_t> slots;

    static uint64_t hash(std::string_view s)
    {
        uint64_t h = 14695981039346656037ull;
        for (unsigned char c : s) {
            h ^= c;
            h *= 1099511628211ull;
        }
        return h;
    }

  public:
    explicit NameIndex(const std::vector<std::string>& n) : names(n)
    {
        require(n.size() < NONE, "too many node names for 32 bit IDs");
        size_t size = 1;
        while (size < n.size() + n.size() / 2 + 1) {
            require(size <= slots.max_size() / 2, "too many names for the node index");
            size *= 2;
        }
        slots.assign(size, NONE);
        for (uint32_t u = 0; u < n.size(); ++u) {
            require(!n[u].empty(), "empty graph node name");
            size_t i = hash(n[u]) & (size - 1);
            while (slots[i] != NONE) {
                require(n[slots[i]] != n[u], "graph node name is repeated");
                i = (i + 1) & (size - 1);
            }
            slots[i] = u;
        }
    }

    uint32_t find(std::string_view key) const
    {
        size_t i = hash(key) & (slots.size() - 1);
        while (slots[i] != NONE) {
            const auto& s = names[slots[i]];
            if (s.size() == key.size() && std::equal(s.begin(), s.end(), key.begin()))
                return slots[i];
            i = (i + 1) & (slots.size() - 1);
        }
        throw dominators::InvalidInput("bubble comparison: unknown node '" + std::string(key) +
                                       "'");
    }
};

inline bool validPole(const std::string& s)
{
    return s.size() >= 2 && (s.back() == '+' || s.back() == '-') &&
           std::all_of(s.begin(), s.end(), [](unsigned char c) { return c >= 33 && c <= 126; });
}

inline bool decimal(const std::string& s, uint32_t& result)
{
    const auto q = std::from_chars(s.data(), s.data() + s.size(), result);
    return !s.empty() && q.ec == std::errc{} && q.ptr == s.data() + s.size() && result != NONE;
}

// Read sorted bubbles and the settings used to find them.
inline Catalogue readCatalogue(const std::string& path, const std::vector<std::string>& names,
                               const dominators::DBubbleIndex& ix)
{
    require(!path.empty() && path != "-", "the bubble input must be a file path");
    require(names.size() * 2 == ix.source && ix.component.size() == names.size() &&
                ix.parent.size() == static_cast<size_t>(ix.source) + 1,
            "the number of node names does not match the dominator tree");
    std::ifstream in(path, std::ios::binary);
    require(bool(in), "cannot open the vg bubble file");
    Catalogue result;
    result.reciprocalEntryBits.assign((static_cast<size_t>(ix.source) + 63) / 64, 0);
    NameIndex ids(names);
    std::string line, lastX, lastY;
    bool signature = false, header = false;
    size_t width = 0;
    while (std::getline(in, line)) {
        require(line.size() <= 65536, "vg bubble row exceeds 65536 bytes");
        if (!line.empty() && line.back() == '\r')
            line.pop_back();
        if (line.empty())
            continue;
        if (line.front() == '#') {
            require(!header && !result.rows, "file settings must come before the column header");
            if (line == "# BubbleFinder vg-snarls catalogue 1") {
                require(!signature && result.suppliedProvenance.empty(),
                        "bubble file header is repeated or misplaced");
                signature = true;
                continue;
            }
            require(signature, "missing vg bubble file header");
            require(line.size() > 2 && line[1] == ' ', "file setting must start with # and a space");
            const auto tab = line.find('\t', 2);
            require(tab != std::string::npos && tab > 2 && tab + 1 < line.size(),
                    "expected setting name, tab and value");
            const std::string key = line.substr(2, tab - 2), value = line.substr(tab + 1);
            require(key.find_first_not_of("abcdefghijklmnopqrstuvwxyz_0123456789") == std::string::npos,
                    "invalid setting name");
            require(
                std::all_of(value.begin(), value.end(), [](unsigned char c) { return c >= 32 && c <= 126; }),
                "invalid setting value");
            require(result.suppliedProvenance.emplace(key, value).second, "file setting is repeated");
            continue;
        }
        require(signature, "missing vg bubble file header");
        if (line == "x\ty" || line == "component\tx\ty") {
            require(!header && !result.rows, "column header is repeated or misplaced");
            header = true;
            width = line == "x\ty" ? 2 : 3;
            continue;
        }
        require(header, "missing bubble column header");
        std::vector<std::string> fields;
        size_t begin = 0;
        for (;;) {
            const auto end = line.find('\t', begin);
            fields.push_back(line.substr(begin, end == std::string::npos ? end : end - begin));
            if (end == std::string::npos)
                break;
            begin = end + 1;
        }
        require(fields.size() == width, "wrong number of columns in vg bubble row");
        const std::string& x = fields[width - 2];
        const std::string& y = fields[width - 1];
        require(validPole(x) && validPole(y) && x < y,
                "bubble ends must be signed and sorted");
        require(!result.rows || lastX < x || (lastX == x && lastY < y),
                "vg bubbles must be sorted without repeats");
        lastX = x;
        lastY = y;
        ++result.rows;
        uint32_t component = NONE;
        if (width == 3)
            require(decimal(fields[0], component), "invalid component number in vg bubble row");
        uint32_t a = 2u * ids.find(std::string_view(x.data(), x.size() - 1)) + uint32_t(x.back() == '-');
        uint32_t b = 2u * ids.find(std::string_view(y.data(), y.size() - 1)) + uint32_t(y.back() == '-');
        require(a / 2 != b / 2, "vg snarls must have two different end nodes");
        const uint32_t actual = ix.component[a / 2];
        require(actual < ix.components && ix.component[b / 2] == actual &&
                    (component == NONE || component == actual),
                "vg bubble ends belong to different components");
        if (a > b)
            std::swap(a, b);
        if (ix.parent[b ^ 1u] == a && ix.parent[a ^ 1u] == b) {
            ++result.commonD;
            result.reciprocalEntryBits[a / 64] |= uint64_t(1) << (a % 64);
            result.reciprocalEntryBits[b / 64] |= uint64_t(1) << (b % 64);
        } else
            result.extra.push_back(Bubble{actual, a, b});
    }
    require(in.eof(), "cannot read the vg bubble file");
    require(signature && header, "missing vg file or column header");
    for (const char* key :
         {"vg_version", "vg_algorithm", "vg_argv", "coordinate_space", "record_filter", "catalogue_scope"})
        require(result.suppliedProvenance.count(key), "required vg setting is missing");
    require(result.suppliedProvenance.at("coordinate_space") == "original_GFA_inward_poles",
            "bubble ends must use GFA names and inward signs");
    require(result.suppliedProvenance.at("catalogue_scope") == "complete_selected_vg_output",
            "bubble file must include all selected vg results");
    require(result.suppliedProvenance.at("vg_algorithm") == "integrated" ||
                result.suppliedProvenance.at("vg_algorithm") == "cactus" ||
                result.suppliedProvenance.at("vg_algorithm") == "default",
            "unsupported vg algorithm in bubble file");
    require(result.suppliedProvenance.at("record_filter") == "exclude_trivial" ||
                result.suppliedProvenance.at("record_filter") == "include_trivial",
            "unknown vg trivial bubble setting");
    require(result.rows == result.commonD + result.extra.size(),
            "vg bubble counts do not add up");
    return result;
}
}
