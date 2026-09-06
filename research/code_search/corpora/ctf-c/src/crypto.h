#ifndef AUTHD_CRYPTO_H
#define AUTHD_CRYPTO_H

#include <stddef.h>

/* XOR each byte of buf[0..len) with key, in place. */
void xor_mask_inplace(char *buf, size_t len, unsigned char key);

/* FNV-1a 32-bit checksum over buf[0..len). */
unsigned int checksum_bytes(const char *buf, size_t len);

#endif /* AUTHD_CRYPTO_H */
