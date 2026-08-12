/*
 * btb_geo.c -- Binary Tree Battle AI geometry acceleration kernel.
 *
 * Pure C11, no third-party dependencies. Loaded from Python via ctypes
 * (see fast_geo.py). Every function is bit-equivalent to the reference
 * Python implementation in AI/aithink4.py, so decision behavior does not
 * change -- only the speed of the hot loops does.
 *
 * Reference Python equivalents (aithink4.py):
 *   _dist(x1,y1,x2,y2)                          -> btb_dist
 *   _pt_seg_dist(px,py,x1,y1,x2,y2)             -> btb_pt_seg_dist
 *   _seg_cross(p1,p2,p3,p4)                     -> btb_seg_cross
 *   _seg_hits_circle(x1,y1,x2,y2,cx,cy,r)       -> btb_seg_hits_circle
 *   _sector(dx,dy)                              -> btb_sector
 *   score_target / _sim_quick_score geometry    -> btb_analyze_moves
 *   threat_penalty / choose_reinforce loop      -> btb_pt_seg_dist_many
 *
 * Build (Windows, TDM-GCC x86_64):
 *   g++ -O2 -shared -static-libgcc -static-libstdc++ -o btb_geo.dll btb_geo.c
 *
 * NOTE: no -ffast-math on purpose; floating point results must match the
 * Python reference bit-for-bit (or within 1 ulp for aggregated sums).
 */

#include <math.h>
#include <stdint.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* g++ compiles .c files as C++: keep the exported names unmangled so
 * ctypes can find them by the plain C symbol names. */
#ifdef __cplusplus
extern "C" {
#endif

#if defined(_WIN32)
#  define BTB_API __declspec(dllexport)
#else
#  define BTB_API __attribute__((visibility("default")))
#endif

/* ------------------------------------------------------------------ */
/* Scalar primitives (bit-equivalent to aithink4.py)                   */
/* ------------------------------------------------------------------ */

/* math.hypot(x2-x1, y2-y1) */
BTB_API double btb_dist(double x1, double y1, double x2, double y2)
{
    return hypot(x2 - x1, y2 - y1);
}

/* aithink4._pt_seg_dist: distance from point to segment */
BTB_API double btb_pt_seg_dist(double px, double py,
                               double x1, double y1, double x2, double y2)
{
    double dx = x2 - x1;
    double dy = y2 - y1;
    double seg_sq = dx * dx + dy * dy;
    if (seg_sq < 1e-9) {
        return hypot(px - x1, py - y1);
    }
    double t = ((px - x1) * dx + (py - y1) * dy) / seg_sq;
    if (t < 0.0) t = 0.0;
    else if (t > 1.0) t = 1.0;
    double cx = x1 + t * dx;
    double cy = y1 + t * dy;
    return hypot(px - cx, py - cy);
}

/* aithink4._orient: cross product sign (exact same arithmetic order) */
static double orient6(double ax, double ay, double bx, double by,
                      double cx, double cy)
{
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
}

/* aithink4._seg_cross: strict intersection, shared endpoints do NOT count */
BTB_API int btb_seg_cross(double x1, double y1, double x2, double y2,
                          double x3, double y3, double x4, double y4)
{
    double o1 = orient6(x1, y1, x2, y2, x3, y3);
    double o2 = orient6(x1, y1, x2, y2, x4, y4);
    double o3 = orient6(x3, y3, x4, y4, x1, y1);
    double o4 = orient6(x3, y3, x4, y4, x2, y2);
    return (o1 * o2 < 0.0) && (o3 * o4 < 0.0) ? 1 : 0;
}

/* aithink4._seg_hits_circle: does segment p1-p2 cross the circle? */
BTB_API int btb_seg_hits_circle(double x1, double y1, double x2, double y2,
                                double cx, double cy, double radius)
{
    return btb_pt_seg_dist(cx, cy, x1, y1, x2, y2) <= radius ? 1 : 0;
}

/* aithink4._sector: map direction vector to 0..7 sector (45 deg each) */
BTB_API int btb_sector(double dx, double dy)
{
    double v = floor(atan2(dy, dx) / M_PI * 4.0) + 8.0;
    int s = (int)v % 8;
    if (s < 0) s += 8;          /* safety, atan2 range keeps v >= 0 anyway */
    return s;
}

/* ------------------------------------------------------------------ */
/* Batch move analysis -- the training hot path.                        */
/*                                                                     */
/* Analyzes k candidate moves in ONE C call. Per move, returns the      */
/* exact statistics that score_target / _sim_quick_score need:          */
/*                                                                     */
/*   out[i*9+0] hit_root      0/1   new branch pierces enemy root       */
/*   out[i*9+1] nodes_hit           enemy nodes pierced                 */
/*   out[i*9+2] hub_value           sum of subtree sizes of pierced     */
/*   out[i*9+3] edges_hit           enemy edges crossed                 */
/*   out[i*9+4] edges_dead          crossed edges with strength<=atk    */
/*   out[i*9+5] spine_cut           pierced nodes/edges on enemy spine  */
/*   out[i*9+6] pinned              enemy expandable nodes in 20<d<55   */
/*   out[i*9+7] collect_value       pickup value within collect radius  */
/*   out[i*9+8] collect_grav        sum value*(1-d/130) for 130>d>=r    */
/*                                                                     */
/* Semantics match aithink4.py exactly: on hit_root the move's node     */
/* loop breaks immediately and no edge/pinned/collect work is done      */
/* (Python `return 10000.0`), the self-endpoint exclusion is a no-op    */
/* because enemy arrays never contain the mover's own points.           */
/* ------------------------------------------------------------------ */
BTB_API void btb_analyze_moves(
    int k, const double *mv,            /* k*5: x1,y1,x2,y2,atk */
    int n_en,
    const double *en_x, const double *en_y,
    const int *en_is_root, const int *en_subtree,
    const int *en_childspace, const int *en_spine,
    int n_eg,
    const double *eg_x1, const double *eg_y1,
    const double *eg_x2, const double *eg_y2,
    const int *eg_st, const int *eg_spine,
    int n_pk,
    const double *pk_x, const double *pk_y, const double *pk_val,
    double node_radius, double collect_dist,
    double *out)                        /* k*9 */
{
    int i, j;
    for (i = 0; i < k; i++) {
        const double *m = mv + i * 5;
        double x1 = m[0], y1 = m[1], x2 = m[2], y2 = m[3];
        int atk = (int)m[4];
        double *o = out + i * 9;
        int hit_root = 0;
        int nodes_hit = 0, edges_hit = 0, edges_dead = 0;
        int spine_cut = 0, pinned = 0;
        double hub_value = 0.0;
        double collect_value = 0.0, collect_grav = 0.0;

        /* --- pierced enemy nodes (break on root hit, like Python) --- */
        for (j = 0; j < n_en; j++) {
            /* Endpoint exclusion, exactly like score_target:
             * an enemy node exactly at the move's src or tgt is skipped.
             * (gen_targets emits tgt == enemy-node positions when aiming
             * to cut a node, so this fires in real games.) */
            if (en_x[j] == x1 && en_y[j] == y1) continue;
            if (en_x[j] == x2 && en_y[j] == y2) continue;
            if (btb_seg_hits_circle(x1, y1, x2, y2,
                                    en_x[j], en_y[j], node_radius)) {
                if (en_is_root[j]) {
                    hit_root = 1;
                    break;
                }
                nodes_hit++;
                hub_value += (double)en_subtree[j];
                if (en_spine[j]) spine_cut++;
            }
        }
        if (hit_root) {
            o[0] = 1.0;
            o[1] = o[2] = o[3] = o[4] = o[5] = o[6] = o[7] = o[8] = 0.0;
            continue;                   /* Python returns 10000.0 early */
        }

        /* --- crossed enemy edges --- */
        for (j = 0; j < n_eg; j++) {
            if (btb_seg_cross(x1, y1, x2, y2,
                              eg_x1[j], eg_y1[j], eg_x2[j], eg_y2[j])) {
                edges_hit++;
                if (eg_st[j] <= atk) edges_dead++;
                if (eg_spine[j]) spine_cut++;
            }
        }

        /* --- pinned: enemy expandable nodes in 20 < d < 55 --- */
        for (j = 0; j < n_en; j++) {
            if (en_childspace[j]) {
                double d = btb_dist(x2, y2, en_x[j], en_y[j]);
                if (d > 20.0 && d < 55.0) pinned++;
            }
        }

        /* --- pickup collection (match the Python loop order) --- */
        for (j = 0; j < n_pk; j++) {
            double d = btb_dist(x2, y2, pk_x[j], pk_y[j]);
            if (d < collect_dist) {
                collect_value += pk_val[j];
            } else if (d < 130.0) {
                collect_grav += pk_val[j] * (1.0 - d / 130.0);
            }
        }

        o[0] = 0.0;
        o[1] = (double)nodes_hit;
        o[2] = hub_value;
        o[3] = (double)edges_hit;
        o[4] = (double)edges_dead;
        o[5] = (double)spine_cut;
        o[6] = (double)pinned;
        o[7] = collect_value;
        o[8] = collect_grav;
    }
}

/* ------------------------------------------------------------------ */
/* Batch point-to-segment distance: one point against n segments.       */
/* ------------------------------------------------------------------ */
BTB_API void btb_pt_seg_dist_many(double px, double py, int n,
                                  const double *x1, const double *y1,
                                  const double *x2, const double *y2,
                                  double *out)
{
    int j;
    for (j = 0; j < n; j++) {
        out[j] = btb_pt_seg_dist(px, py, x1[j], y1[j], x2[j], y2[j]);
    }
}

/* ------------------------------------------------------------------ */
/* Batch distances from one fixed point to n points.                   */
/* Used by _sim_best_move to compute d_to/d_from for every candidate   */
/* in one C call (the reference Python loop calls _dist per candidate).*/
/* ------------------------------------------------------------------ */
BTB_API void btb_dists_to(double px, double py, int n,
                          const double *xs, const double *ys, double *out)
{
    int j;
    for (j = 0; j < n; j++) {
        out[j] = hypot(xs[j] - px, ys[j] - py);
    }
}

/* ------------------------------------------------------------------ */
/* Distance grid: every point against every segment.                   */
/* out[i*n_seg + j] = dist(point i, segment j).                        */
/* Used by threat_penalty: my nodes (points) vs enemy extension        */
/* segments (e -> target).                                             */
/* ------------------------------------------------------------------ */
BTB_API void btb_pt_seg_dist_grid(
    int n_pts, const double *px, const double *py,
    int n_seg, const double *sx1, const double *sy1,
    const double *sx2, const double *sy2,
    double *out)
{
    int i, j;
    for (i = 0; i < n_pts; i++) {
        for (j = 0; j < n_seg; j++) {
            out[i * n_seg + j] = btb_pt_seg_dist(
                px[i], py[i], sx1[j], sy1[j], sx2[j], sy2[j]);
        }
    }
}

#ifdef __cplusplus
}
#endif
