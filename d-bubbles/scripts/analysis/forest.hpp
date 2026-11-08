#pragma once
#include <algorithm>
#include <cstddef>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace dbubble {
namespace full_static_v1 {
using Index = std::size_t;
inline constexpr Index NONE = std::numeric_limits<Index>::max();

inline void refuse(const char* code, const char* message)
{
    throw std::runtime_error(std::string(code) + ": " + message);
}

namespace detail {
inline Index checked_add(Index a, Index b)
{
    if (b > std::numeric_limits<Index>::max() - a)
        refuse("overflow", "array size exceeds the integer limit");
    return a + b;
}

class Forest
{
  public:
    std::vector<Index> parent, tin, tout, at, depth, head, order;
    std::vector<Index> offset, children;

    explicit Forest(const std::vector<Index>& p) : parent(p)
    {
        const Index n = p.size();
        offset.assign(checked_add(n, 1), 0);
        std::vector<Index> roots;
        for (Index i = 0; i < n; ++i) {
            if (p[i] == NONE)
                roots.push_back(i);
            else {
                if (p[i] >= n || p[i] == i)
                    refuse("forest", "a parent is outside the forest or points to itself");
                ++offset[p[i] + 1];
            }
        }
        for (Index i = 1; i <= n; ++i)
            offset[i] += offset[i - 1];
        children.resize(offset[n]);
        auto cursor = offset;
        for (Index i = 0; i < n; ++i)
            if (p[i] != NONE)
                children[cursor[p[i]]++] = i;
        depth.assign(n, 0);
        std::vector<Index> stack(roots.rbegin(), roots.rend());
        order.reserve(n);
        while (!stack.empty()) {
            Index v = stack.back();
            stack.pop_back();
            order.push_back(v);
            for (Index k = offset[v]; k < offset[v + 1]; ++k) {
                Index c = children[k];
                depth[c] = checked_add(depth[v], 1);
                stack.push_back(c);
            }
        }
        if (order.size() != n)
            refuse("forest", "the forest contains a cycle");
        std::vector<Index> subtree(n, 1), heavy(n, NONE);
        for (auto it = order.rbegin(); it != order.rend(); ++it) {
            Index v = *it;
            for (Index k = offset[v]; k < offset[v + 1]; ++k) {
                Index c = children[k];
                subtree[v] = checked_add(subtree[v], subtree[c]);
                if (heavy[v] == NONE || subtree[c] > subtree[heavy[v]])
                    heavy[v] = c;
            }
        }
        tin.resize(n);
        tout.resize(n);
        head.resize(n);
        at.reserve(n);
        stack.assign(roots.rbegin(), roots.rend());
        for (Index r : roots)
            head[r] = r;
        while (!stack.empty()) {
            Index v = stack.back();
            stack.pop_back();
            tin[v] = at.size();
            at.push_back(v);
            // Visit the largest child first.
            for (Index k = offset[v + 1]; k > offset[v]; --k) {
                Index c = children[k - 1];
                if (c != heavy[v]) {
                    head[c] = c;
                    stack.push_back(c);
                }
            }
            if (heavy[v] != NONE) {
                head[heavy[v]] = head[v];
                stack.push_back(heavy[v]);
            }
        }
        for (Index v = 0; v < n; ++v)
            tout[v] = tin[v] + subtree[v];
    }

    Index lca(Index a, Index b) const
    {
        if (a == NONE || b == NONE)
            return NONE;
        while (head[a] != head[b]) {
            if (depth[head[a]] < depth[head[b]])
                std::swap(a, b);
            a = parent[head[a]];
            if (a == NONE)
                return NONE;
        }
        return depth[a] < depth[b] ? a : b;
    }
};
}
}
}
