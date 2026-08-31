# Makefile for the synthetic authd corpus (CTF-style pwn target).
#
# Not required for the search benchmarks (the harness measures text
# search over these sources, not the built binary), but kept so the
# corpus stays a coherent, buildable project.

CC      ?= cc
CFLAGS  ?= -O2 -Wall -Wextra -fno-stack-protector -z execstack
SRCS     := $(wildcard src/*.c)
OBJS     := $(SRCS:.c=.o)
TARGET   := authd

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $(OBJS)

src/%.o: src/%.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f $(OBJS) $(TARGET)

.PHONY: all clean
