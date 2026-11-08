#pragma once
#include "catalogue.hpp"
#include "split.hpp"
#include <array>
#include <utility>

namespace paper_compare {
namespace detail {
struct Euler
{
    std::vector<uint32_t> tin, end, order;

    explicit Euler(const dominators::DBubbleIndex& ix)
        : tin(ix.parent.size(), NONE), end(ix.parent.size(), NONE)
    {
        const size_t size = ix.parent.size();
        require(ix.source + 1ull == size && ix.parent[ix.source] == NONE,
                "graph size does not match the source tree");
        std::vector<uint32_t> first(size, NONE), next(size, NONE);
        uint64_t edges = 0;
        for (uint32_t u = 0; u < ix.source; ++u)
            if (ix.parent[u] != NONE) {
                require(ix.parent[u] < size && ix.parent[u] != u,
                        "a source tree parent is outside the tree or points to itself");
                next[u] = first[ix.parent[u]];
                first[ix.parent[u]] = u;
                ++edges;
            }
        require(edges == ix.reachableStates, "tree parent count differs from the reachable node count");
        order.reserve(static_cast<size_t>(edges) + 1);
        uint32_t u = ix.source;
        bool entering = true;
        while (true) {
            if (entering) {
                require(tin[u] == NONE && order.size() < NONE,
                        "source tree walk visited a node twice or exceeded 32 bit IDs");
                tin[u] = static_cast<uint32_t>(order.size());
                order.push_back(u);
                if (first[u] != NONE) {
                    u = first[u];
                    continue;
                }
            }
            end[u] = static_cast<uint32_t>(order.size());
            if (u == ix.source)
                break;
            if (next[u] != NONE) {
                u = next[u];
                entering = true;
            } else {
                u = ix.parent[u];
                entering = false;
            }
        }
        require(order.size() == edges + 1, "source tree walk did not visit every node");
    }

    bool ancestor(uint32_t a, uint32_t z) const
    {
        return a < tin.size() && z < tin.size() && tin[a] != NONE && tin[z] != NONE && tin[a] <= tin[z] &&
               tin[z] < end[a];
    }

    std::array<std::pair<uint32_t, uint32_t>, 2> difference(uint32_t a, uint32_t child) const
    {
        require(a < tin.size() && child < tin.size() && a != child && ancestor(a, child),
                "the removed subtree must start below the selected ancestor");
        return {{{tin[a], tin[child]}, {end[child], end[a]}}};
    }

    bool interior(const Bubble& p, uint32_t z) const
    {
        return ancestor(p.x, z) && !ancestor(p.y ^ 1u, z) && ancestor(p.y, z ^ 1u) &&
               !ancestor(p.x ^ 1u, z ^ 1u);
    }
};

struct DBody
{
    Bubble boundary;
    std::vector<uint32_t> members, times;
};

inline DBody body(const Euler& e, const Bubble& p)
{
    DBody result;
    result.boundary = p;
    const auto forward = e.difference(p.x, p.y ^ 1u), reverse = e.difference(p.y, p.x ^ 1u);
    const auto count = [](const auto& r) {
        return uint64_t(r[0].second - r[0].first) + r[1].second - r[1].first;
    };
    const bool flip = count(reverse) < count(forward);
    const auto& ranges = flip ? reverse : forward;
    for (const auto& r : ranges)
        for (uint32_t i = r.first; i < r.second; ++i) {
            uint32_t z = e.order[i];
            require(z + 1u < e.tin.size(), "the bubble region includes the added source node");
            if (flip)
                z ^= 1u;
            if (e.interior(p, z)) {
                result.members.push_back(z / 2);
            }
        }
    result.members.push_back(p.x / 2);
    result.members.push_back(p.y / 2);
    std::sort(result.members.begin(), result.members.end());
    result.members.erase(std::unique(result.members.begin(), result.members.end()), result.members.end());
    return result;
}

inline bool member(const vg_native_split::Index& ix, const vg_native_split::Result& r, uint32_t u)
{
    return u == r.a || u == r.b || ix.full_R_contains(r, u);
}
}
}
