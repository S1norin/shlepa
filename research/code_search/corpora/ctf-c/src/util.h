#ifndef AUTHD_UTIL_H
#define AUTHD_UTIL_H

#include <stddef.h>

/* Read one line from stdin into buf. Return 1 on a line, 0 at EOF. */
int read_line(char *buf, size_t buf_size);

/* Strip leading/trailing spaces and tabs in place; return s. */
char *trim(char *s);

#endif /* AUTHD_UTIL_H */
