/*
 * Flag-reveal code path.
 *
 * The flag is assembled from two fragments and printed. This is the
 * "planted" function the binary-exploitation player would call by
 * jumping to it (non-PIE build, fixed address).
 */
#include <stdio.h>

#include "flag.h"

static const char FLAG_PART_A[] = "ctf{stack_";
static const char FLAG_PART_B[] = "pivot_2026}";

void reveal_flag(void)
{
    char flag[64];
    size_t n = 0;

    const char *p = FLAG_PART_A;
    while (*p && n < sizeof flag - 1) {
        flag[n++] = *p++;
    }
    p = FLAG_PART_B;
    while (*p && n < sizeof flag - 1) {
        flag[n++] = *p++;
    }
    flag[n] = '\0';

    printf("FLAG %s\n", flag);
}
