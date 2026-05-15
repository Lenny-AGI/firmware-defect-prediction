# 工业网关项目 Makefile（用于验证编译）
CC = arm-none-eabi-gcc
LD = arm-none-eabi-ld
OBJCOPY = arm-none-eabi-objcopy

CFLAGS = -mcpu=cortex-m4 -mthumb -O2 -Wall -Wextra \
         -I./src -I./src/drivers -I./src/freertos \
         -DFIRMDEFECT_DEMO

LDFLAGS = -mcpu=cortex-m4 -mthumb -T./ld/stm32f4.ld

SRCS = src/main.c src/drivers/uart_driver.c
OBJS = $(SRCS:.c=.o)
TARGET = build/firmware.elf

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(OBJS) | build
	$(CC) $(LDFLAGS) -o $@ $^

build:
	mkdir -p build

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -rf build $(OBJS)
