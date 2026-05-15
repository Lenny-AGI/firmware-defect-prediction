#ifndef UART_DRIVER_H
#define UART_DRIVER_H

#include <stdint.h>

void uart_init(uint32_t base, uint32_t baud);
void uart_send(uint32_t base, const uint8_t *data, uint32_t len);
void uart_tx_enqueue(uint8_t byte);
uint8_t uart_tx_dequeue(void);

#endif /* UART_DRIVER_H */
