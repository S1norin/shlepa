#ifndef AUTHD_LOG_H
#define AUTHD_LOG_H

/* Set the daemon name used as the log prefix. */
void log_init(const char *name);

/* Append one formatted audit line to stderr. */
void log_event(const char *fmt, ...);

#endif /* AUTHD_LOG_H */
