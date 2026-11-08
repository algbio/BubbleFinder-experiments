// Compare the bubbles listed by Billi, BubbleFinder and vg.
#include <algorithm>
#include <charconv>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

using U = std::uint64_t;

void need(bool p, const char* s)
{
    if (!p)
        throw std::runtime_error(s);
}

std::vector<std::string_view> fields(const std::string& s)
{
    std::vector<std::string_view> r;
    std::size_t p = 0;
    for (;;) {
        auto q = s.find('\t', p);
        r.emplace_back(s.data() + p, (q == s.npos ? s.size() : q) - p);
        if (q == s.npos)
            break;
        p = q + 1;
    }
    return r;
}

std::uint32_t number(std::string_view s)
{
    U v = 0;
    auto q = std::from_chars(s.data(), s.data() + s.size(), v);
    need(!s.empty() && q.ec == std::errc{} && q.ptr == s.data() + s.size() && v > 0 && v < 0x80000000ULL,
         "node ID must be an integer from 1 to 2147483647");
    return std::uint32_t(v);
}

std::map<std::string, std::uint32_t> mapping(const char* path)
{
    std::map<std::string, std::uint32_t> m;
    if (std::string(path) == "-")
        return m;

    std::ifstream f(path);
    need(bool(f), "cannot open the node translation file");
    std::string s;
    while (std::getline(f, s)) {
        auto a = fields(s);
        need(a.size() == 3 && a[0] == "T", "vg name map rows need T, name and ID columns");
        need(m.emplace(std::string(a[1]), number(a[2])).second, "node name map repeats a name");
    }
    need(f.eof(), "cannot read the node translation file");
    return m;
}

U key(std::uint32_t a, std::uint32_t b)
{
    if (a > b)
        std::swap(a, b);
    return (U(a) << 32) | b;
}

std::uint32_t pole(std::string_view s)
{
    need(s.size() > 1 && (s.back() == '+' || s.back() == '-'),
         "bubble end needs a node ID and + or -");
    return 2 * number(s.substr(0, s.size() - 1)) + (s.back() == '-');
}

void unique(std::vector<U>& v)
{
    std::sort(v.begin(), v.end());
    v.erase(std::unique(v.begin(), v.end()), v.end());
}

bool has(const std::vector<U>& v, U k)
{
    return std::binary_search(v.begin(), v.end(), k);
}

std::vector<U> bubbles(const char* path, bool d, U& rows, U& unary)
{
    std::ifstream f(path);
    need(bool(f), "cannot open the bubble file");
    std::string s;
    std::vector<U> v;
    while (std::getline(f, s)) {
        if (s.empty() || s[0] == '#' || s == "component\tx\ty" || s == "x\ty")
            continue;
        auto a = fields(s);
        need(a.size() == (d ? 3 : 2), "wrong number of columns in bubble row");
        auto x = pole(a[a.size() - 2]), y = pole(a.back());
        ++rows;
        if (x / 2 == y / 2) {
            ++unary;
            continue;
        }
        v.push_back(key(x, y));
    }
    need(f.eof(), "cannot read the bubble file");
    unique(v);
    return v;
}

struct Billi
{
    std::vector<U> v;
    U bb = 0, hp = 0, unary = 0;
};

Billi billi(const char* path, const std::map<std::string, std::uint32_t>& m)
{
    std::ifstream f(path);
    need(bool(f), "cannot open the Billi output");
    std::string s;
    Billi r;
    while (std::getline(f, s)) {
        if (s.empty())
            continue;
        auto a = fields(s);
        if (a[0] == "HP") {
            ++r.hp;
            continue;
        }
        if (a[0] != "BB")
            continue;

        need(a.size() == 7, "Billi BB row needs seven columns");
        ++r.bb;
        auto node = [&](std::string_view t) {
            need(t.size() > 1 && (t.front() == '<' || t.front() == '>'), "a Billi node must start with < or >");
            auto name = t.substr(1);
            if (m.empty())
                return number(name);
            auto p = m.find(std::string(name));
            need(p != m.end(), "Billi node is missing from the name map");
            return p->second;
        };
        auto x = 2 * node(a[4]) + (a[4].front() == '<'), y = 2 * node(a[5]) + (a[5].front() == '>');
        if (x / 2 == y / 2) {
            ++r.unary;
            continue;
        }
        r.v.push_back(key(x, y));
    }
    need(f.eof(), "cannot read the Billi output");
    unique(r.v);
    return r;
}

std::string printed(std::uint32_t x)
{
    return std::to_string(x / 2) + (x % 2 ? "-" : "+");
}

int main(int argc, char** argv)
{
    try {
        if (argc == 2 && std::string(argv[1]) == "--selftest") {
            need(key(pole("11+"), pole("23-")) == key(22, 47),
                    "wrong IDs for signed bubble ends");
            need(key(22, 47) != key(23, 46), "opposite signs produced the same bubble ID");
            need(2 * number("11") + std::uint32_t('<' == '<') == 23,
                    "wrong sign for the first Billi end");
            need(2 * number("23") + std::uint32_t('>' == '>') == 47,
                    "wrong sign for the second Billi end");
            std::cout << "PASS\n";
            return 0;
        }
        need(argc == 8, "join D VG_ALL VG_NONTRIV EMPTY BILLI TRANSLATION OUTSIDE");

        U dr = 0, du = 0, vr = 0, vu = 0, nr = 0, nu = 0, er = 0, eu = 0;
        auto d = bubbles(argv[1], true, dr, du), v = bubbles(argv[2], false, vr, vu),
             n = bubbles(argv[3], false, nr, nu), e = bubbles(argv[4], false, er, eu);
        auto b = billi(argv[5], mapping(argv[6]));
        U extra = 0, dropped = 0, nonempty_dropped = 0, common = 0;
        for (U k : n) {
            extra += !has(v, k);
            common += has(d, k);
        }
        for (U k : v)
            if (!has(n, k)) {
                ++dropped;
                nonempty_dropped += !has(e, k);
            }

        std::ofstream out(argv[7]);
        need(bool(out), "cannot open the file for Billi bubbles missing from vg");
        out << "x\ty\tin_raw_D\n";
        U atoms[4] = {}, trivial = 0, outside = 0;
        for (U k : b.v) {
            bool dd = has(d, k), vv = has(n, k);
            if (vv) {
                ++atoms[1 + 2 * dd];
                continue;
            }
            if (has(v, k)) {
                ++trivial;
                continue;
            }
            ++outside;
            out << printed(std::uint32_t(k >> 32)) << '\t' << printed(std::uint32_t(k)) << '\t' << dd << '\n';
        }
        out.close();
        need(bool(out), "cannot finish writing Billi bubbles missing from vg");

        std::cout << "{\"checks\":\"" << (extra == 0 && nonempty_dropped == 0 ? "PASS" : "FILTER_NEEDS_NATIVE_CHECK")
                  << "\",\"raw_D_rows\":" << dr << ",\"raw_D_unique\":" << d.size() << ",\"raw_D_unary\":" << du
                  << ",\"vg_all_rows\":" << vr << ",\"vg_all_unique\":" << v.size() << ",\"vg_all_unary\":" << vu
                  << ",\"vg_nontrivial_unique\":" << n.size()
                  << ",\"vg_nontrivial_absent_in_all\":" << extra << ",\"vg_dropped\":" << dropped
                  << ",\"vg_dropped_not_signed_empty\":" << nonempty_dropped
                  << ",\"D_raw_intersect_vg_nontrivial\":" << common
                  << ",\"Billi_BB_rows\":" << b.bb << ",\"Billi_HP_rows\":" << b.hp << ",\"Billi_unary_rows\":" << b.unary
                  << ",\"Billi_unique_nonunary\":" << b.v.size() << ",\"Billi_duplicates\":" << b.bb - b.unary - b.v.size()
                  << ",\"Billi_trivial_vg_pairs\":" << trivial
                  << ",\"Billi_vg_only\":" << atoms[1] << ",\"Billi_D_and_vg\":" << atoms[3]
                  << ",\"Billi_absent_vg_all\":" << outside << "}\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
