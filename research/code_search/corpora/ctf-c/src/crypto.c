/*
 * Small byte transforms used by the input path and token minting.
 */
#include <stddef.h>

#include "crypto.h"

void xor_mask_inplace(char *buf, size_t len, unsigned char key)
{
    for (size_t i = 0; i < len; i++) {
        buf[i] = (char)((unsigned char)buf[i] ^ key);
    }
}

unsigned int checksum_bytes(const char *buf, size_t len)
{
    /* FNV-1a, 32-bit. */
    unsigned int h = 2166136261u;
    for (size_t i = 0; i < len; i++) {
        h ^= (unsigned char)buf[i];
        h *= 16777619u;
    }
    return h;
}
