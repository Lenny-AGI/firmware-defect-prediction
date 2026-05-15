/**
 * industrial_gateway/main.c
 * 工业网关固件 — FreeRTOS 多任务示例
 * 包含故意植入的缺陷用于 FirmDefect 演示
 *
 * 缺陷清单:
 * [DF001] 数据竞争: g_sensor_data 无保护跨任务访问
 * [DF002] 潜在死锁: task_eth_rx 嵌套获取锁顺序不一致
 * [DF003] 栈溢出: task_logger 栈仅 128 字节
 * [DF004] 优先级反转: 互斥量未启用优先级继承
 * [DF005] ISR安全: DMA_IRQHandler 直接访问共享缓冲区
 * [DF006] 堆损坏: 不匹配的 malloc/free 模式
 * [DF007] 缓冲区溢出: 固定大小数组无边界检查
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"
#include "queue.h"

/* ==================== 硬件抽象 ==================== */
#define UART_BASE       0x40004000
#define ETH_BASE        0x40008000
#define DMA_BASE        0x4000C000
#define GPIO_BASE       0x40020000

/* ==================== 共享资源 ==================== */

/* [DF001] 数据竞争: 多任务无锁访问 */
static volatile uint32_t g_sensor_data[16];
static volatile uint32_t g_sensor_index = 0;

/* 共享数据缓冲区 - ISR与任务共享 [DF005] */
static uint8_t g_dma_buffer[2048];
static volatile uint32_t g_dma_index = 0;

/* [DF006] 堆损坏: 不匹配的分配/释放模式 */
static uint8_t *g_packet_buffer = NULL;

/* ==================== 同步原语 ==================== */

SemaphoreHandle_t xEthMutex = NULL;
SemaphoreHandle_t xSensorMutex = NULL;
SemaphoreHandle_t xLogMutex = NULL;    /* [DF004] 未启用优先级继承 */
QueueHandle_t xPacketQueue = NULL;

/* ==================== 任务函数 ==================== */

/**
 * 传感器数据采集任务 — 高优先级
 * 周期读取传感器并更新全局数据
 */
void vSensorTask(void *pvParameters) {
    uint32_t sensor_val;
    BaseType_t xDelay = pdMS_TO_TICKS(10);

    for (;;) {
        /* 模拟读取传感器 */
        sensor_val = rand() % 0xFFFF;

        /* [DF001] 写入g_sensor_data未加锁 */
        g_sensor_data[g_sensor_index % 16] = sensor_val;
        g_sensor_index++;

        vTaskDelay(xDelay);
    }
}

/**
 * 数据上报任务 — 中优先级
 * 读取传感器数据并上报
 */
void vReportTask(void *pvParameters) {
    uint32_t local_data[16];
    BaseType_t xDelay = pdMS_TO_TICKS(50);

    for (;;) {
        /* [DF001] 读取g_sensor_data也未加锁 -> 数据竞争 */
        memcpy(local_data, g_sensor_data, sizeof(g_sensor_data));

        /* 处理数据... */
        process_sensor_data(local_data, 16);

        vTaskDelay(xDelay);
    }
}

/**
 * 以太网接收任务 — 中低优先级
 * 处理网络数据包
 */
void vEthRxTask(void *pvParameters) {
    uint8_t rx_buffer[1518];
    BaseType_t xDelay = pdMS_TO_TICKS(5);

    for (;;) {
        /* 等待网卡中断或轮询 */
        if (xSemaphoreTake(xEthMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
            /* [DF002] 持有xEthMutex时获取xLogMutex */
            if (xSemaphoreTake(xLogMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
                read_eth_packet(rx_buffer, sizeof(rx_buffer));

                /* [DF006] 不匹配的分配: malloc但未free */
                g_packet_buffer = (uint8_t *)malloc(1518);
                memcpy(g_packet_buffer, rx_buffer, 1518);

                xSemaphoreGive(xLogMutex);
            }
            xSemaphoreGive(xEthMutex);
        }

        /* [DF007] 潜在缓冲区溢出 */
        process_command(rx_buffer, sizeof(rx_buffer));

        vTaskDelay(xDelay);
    }
}

/**
 * 日志记录任务 — 低优先级
 * 将系统日志写入UART
 */
void vLoggerTask(void *pvParameters) {
    /* [DF003] 栈仅128字节 */
    char log_buffer[128];
    uint32_t log_index = 0;

    for (;;) {
        if (xSemaphoreTake(xLogMutex, portMAX_DELAY) == pdTRUE) {
            /* 构造日志字符串 — 可能超过128字节 [DF003] */
            snprintf(log_buffer, sizeof(log_buffer),
                     "[%lu] sensor=%lu eth_pkt=%lu dma_idx=%lu",
                     log_index++, g_sensor_data[0],
                     (unsigned long)g_packet_buffer,
                     g_dma_index);

            uart_send(UART_BASE, log_buffer, strlen(log_buffer));
            xSemaphoreGive(xLogMutex);
        }
    }
}

/**
 * 命令处理任务 — 最低优先级
 * 处理从串口/网口收到的命令
 */
void vCmdTask(void *pvParameters) {
    uint8_t cmd_buf[64];

    for (;;) {
        if (xQueueReceive(xPacketQueue, cmd_buf, portMAX_DELAY) == pdTRUE) {
            /* [DF002] 反向锁获取顺序: xLogMutex先于xEthMutex -> 死锁风险 */
            if (xSemaphoreTake(xLogMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
                if (xSemaphoreTake(xEthMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
                    execute_cmd(cmd_buf);
                    xSemaphoreGive(xEthMutex);
                }
                xSemaphoreGive(xLogMutex);
            }
        }
    }
}

/* ==================== ISR ==================== */

/**
 * DMA传输完成中断 — [DF005]
 * 直接访问共享缓冲区而无适当的同步
 */
void DMA_IRQHandler(void) {
    BaseType_t xHigherPriorityTaskWoken = pdFALSE;
    uint32_t dma_status = *(volatile uint32_t *)(DMA_BASE + 0x00);

    if (dma_status & 0x01) {
        /* 直接写入共享缓冲区 — ISR不安全 */
        /* FirmDefect: ISR访问g_dma_buffer未使用FromISR API */
        g_dma_buffer[g_dma_index % 2048] = (uint8_t)(dma_status >> 8);
        g_dma_index++;

        /* 通知处理任务 — 正确做法 */
        vTaskNotifyGiveFromISR(xEthTaskHandle, &xHigherPriorityTaskWoken);
    }

    *(volatile uint32_t *)(DMA_BASE + 0x00) = dma_status;
    portYIELD_FROM_ISR(xHigherPriorityTaskWoken);
}

/**
 * 定时器中断 — 用于系统节拍
 */
void TIM3_IRQHandler(void) {
    /* 正确的ISR实现 */
    *(volatile uint32_t *)(0x40000400) = 0;
}

/* ==================== 辅助函数 ==================== */

static void process_sensor_data(uint32_t *data, uint32_t len) {
    for (uint32_t i = 0; i < len; i++) {
        data[i] = data[i] & 0xFF;  /* 简单处理 */
    }
}

static void read_eth_packet(uint8_t *buf, uint32_t len) {
    /* 模拟读取以太网包 */
    memset(buf, 0, len);
}

/* [DF007] 固定大小数组处理无边界检查 */
static void process_command(uint8_t *cmd, uint32_t len) {
    char resp_buf[64];  /* 固定64字节 */

    /* 无边界检查的拷贝 — 若cmd包含超过64字节的响应，会溢出 */
    for (int i = 0; i < (int)len; i++) {
        if (cmd[i] == '\n') break;
        /* 响应可能超过64字节，无边界检查 */
        if (i < 64) {
            resp_buf[i] = cmd[i];
        }
    }
}

static void execute_cmd(uint8_t *cmd) {
    /* 执行命令 */
    uart_send(UART_BASE, "CMD_OK\n", 7);
}

static void uart_send(uint32_t base, const char *data, uint32_t len) {
    /* 模拟UART发送 */
    (void)base;
    (void)data;
    (void)len;
}

/* ==================== 任务句柄 ==================== */
TaskHandle_t xSensorTaskHandle = NULL;
TaskHandle_t xEthRxTaskHandle = NULL;
TaskHandle_t xReportTaskHandle = NULL;
TaskHandle_t xLoggerTaskHandle = NULL;
TaskHandle_t xEthTxTask = NULL;  /* 未使用的变量 */

/* ==================== 系统初始化 ==================== */

void vApplicationSetup(void) {
    /* 创建互斥量 */
    xEthMutex = xSemaphoreCreateMutex();
    xSensorMutex = xSemaphoreCreateMutex();
    xLogMutex = xSemaphoreCreateBinary();  /* [DF004] 二值信号量不如互斥量 */

    /* 创建队列 */
    xPacketQueue = xQueueCreate(10, 64);

    /* 创建任务 */
    xTaskCreate(vSensorTask, "Sensor", 256, NULL, 1, &xSensorTaskHandle);
    xTaskCreate(vReportTask, "Report", 512, NULL, 2, &xReportTaskHandle);
    xTaskCreate(vEthRxTask, "EthRx", 512, NULL, 3, &xEthRxTaskHandle);
    xTaskCreate(vLoggerTask, "Logger", 128, NULL, 4, &xLoggerTaskHandle);  /* [DF003] 栈128 < 512 */
    xTaskCreate(vCmdTask, "Cmd", 256, NULL, 5, NULL);

    /* 启动调度器 */
    vTaskStartScheduler();
}

int main(void) {
    vApplicationSetup();
    /* 不会到达这里 */
    return 0;
}
