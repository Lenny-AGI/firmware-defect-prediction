/**
 * UART驱动 — 工业网关串口驱动
 * 包含故意植入的缺陷: 共享寄存器无保护
 */
#include "uart_driver.h"

/* UART寄存器映射 */
#define UART_DR(x)      (*(volatile uint32_t *)((x) + 0x00))
#define UART_SR(x)      (*(volatile uint32_t *)((x) + 0x04))
#define UART_CR(x)      (*(volatile uint32_t *)((x) + 0x08))

/* UART状态标志 */
#define UART_SR_TXE     (1 << 7)
#define UART_SR_TC      (1 << 6)
#define UART_SR_RXNE    (1 << 5)

/* 共享发送缓冲区（多任务访问无保护）*/
static uint8_t uart_tx_buffer[256];
static volatile uint32_t uart_tx_head = 0;
static volatile uint32_t uart_tx_tail = 0;

void uart_init(uint32_t base, uint32_t baud) {
    /* 配置波特率 */
    UART_CR(base) = 0x01;  /* 使能UART */

    /* FirmDefect: uart_tx_buffer为全局共享，多个任务可能同时写 */
    uart_tx_head = 0;
    uart_tx_tail = 0;
}

void uart_send(uint32_t base, const uint8_t *data, uint32_t len) {
    /* 轮询发送 */
    for (uint32_t i = 0; i < len; i++) {
        /* 等待发送保持寄存器空 */
        while (!(UART_SR(base) & UART_SR_TXE));
        UART_DR(base) = data[i];
    }
}

/* [隐藏缺陷] 无锁的环形缓冲区写入 — ISR和任务都调用 */
void uart_tx_enqueue(uint8_t byte) {
    /* 无互斥保护 — 多任务/ISR同时写入导致数据竞争 */
    uint32_t next = (uart_tx_head + 1) % 256;
    if (next != uart_tx_tail) {
        uart_tx_buffer[uart_tx_head] = byte;
        uart_tx_head = next;
    }
}

uint8_t uart_tx_dequeue(void) {
    uint8_t byte = 0;
    if (uart_tx_tail != uart_tx_head) {
        byte = uart_tx_buffer[uart_tx_tail];
        uart_tx_tail = (uart_tx_tail + 1) % 256;
    }
    return byte;
}
