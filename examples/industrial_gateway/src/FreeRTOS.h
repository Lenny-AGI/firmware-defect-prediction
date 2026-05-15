/**
 * FreeRTOS 头文件桩 — 仅供FirmDefect解析使用
 */
#ifndef FREERTOS_H
#define FREERTOS_H

#include <stdint.h>
#include <stddef.h>

typedef unsigned long TickType_t;
typedef unsigned long BaseType_t;
typedef uint32_t UBaseType_t;

struct tskTaskControlBlock;
typedef struct tskTaskControlBlock *TaskHandle_t;

struct QueueDefinition;
typedef struct QueueDefinition *QueueHandle_t;
typedef struct QueueDefinition *SemaphoreHandle_t;

#define pdTRUE         1
#define pdFALSE        0
#define pdPASS         pdTRUE
#define pdFAIL         pdFALSE
#define pdMS_TO_TICKS(x) ((TickType_t)(x))
#define portMAX_DELAY  ((TickType_t)0xFFFFFFFFUL)
#define portYIELD_FROM_ISR(x) do { if(x) {} } while(0)
#define configASSERT(x)

/* 任务 API */
void vTaskStartScheduler(void);
void vTaskDelay(const TickType_t xTicksToDelay);
void vTaskNotifyGiveFromISR(TaskHandle_t xTaskToNotify, BaseType_t *pxHigherPriorityTaskWoken);
BaseType_t xTaskCreate(void (*pvTaskCode)(void*), const char *pcName,
                       uint16_t usStackDepth, void *pvParameters,
                       UBaseType_t uxPriority, TaskHandle_t *pxCreatedTask);

/* 信号量 API */
SemaphoreHandle_t xSemaphoreCreateMutex(void);
SemaphoreHandle_t xSemaphoreCreateBinary(void);
SemaphoreHandle_t xSemaphoreCreateRecursiveMutex(void);
BaseType_t xSemaphoreTake(SemaphoreHandle_t xSemaphore, TickType_t xBlockTime);
BaseType_t xSemaphoreGive(SemaphoreHandle_t xSemaphore);
BaseType_t xSemaphoreGiveFromISR(SemaphoreHandle_t xSemaphore,
                                 BaseType_t *pxHigherPriorityTaskWoken);

/* 队列 API */
QueueHandle_t xQueueCreate(UBaseType_t uxQueueLength, UBaseType_t uxItemSize);
BaseType_t xQueueSend(QueueHandle_t xQueue, const void *pvItemToQueue,
                      TickType_t xTicksToWait);
BaseType_t xQueueReceive(QueueHandle_t xQueue, void *pvBuffer,
                         TickType_t xTicksToWait);
BaseType_t xQueueSendFromISR(QueueHandle_t xQueue, const void *pvItemToQueue,
                             BaseType_t *pxHigherPriorityTaskWoken);

/* 任务通知 */
BaseType_t xTaskNotifyFromISR(TaskHandle_t xTaskToNotify, uint32_t ulValue,
                               uint8_t ucAction, BaseType_t *pxHigherPriorityTaskWoken);
BaseType_t xTaskNotifyGiveFromISR(TaskHandle_t xTaskToNotify,
                                   BaseType_t *pxHigherPriorityTaskWoken);

/* 内存 */
void *pvPortMalloc(size_t xWantedSize);
void vPortFree(void *pv);
void vApplicationMallocFailedHook(void);

#endif /* FREERTOS_H */
