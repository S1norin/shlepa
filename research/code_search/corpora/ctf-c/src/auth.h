#ifndef AUTHD_AUTH_H
#define AUTHD_AUTH_H

/*
 * Return the matched role for (username, password):
 *   1  admin
 *   0  regular user
 *  -1  no match
 */
int auth_check(const char *username, const char *password);

#endif /* AUTHD_AUTH_H */
