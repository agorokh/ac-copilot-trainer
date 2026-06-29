// Setup Exchange browser -- issue #363.
//
// The screen sends `se.search` and `se.download` requests through main.cpp's
// WebSocket drain. The Python sidecar owns the HTTP proxy and safe install;
// once a download ack returns, main.cpp asks the Lua app to `setup.load` the
// installed INI path.

#pragma once

#include <lvgl.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

lv_obj_t* screen_setup_exchange_create(void);

void screen_setup_exchange_set_context(const char* car_id, const char* car_name,
                                       const char* track_id, const char* track_name);
void screen_setup_exchange_clear_results(void);
void screen_setup_exchange_add_result(int32_t setup_id,
                                      const char* name,
                                      const char* author,
                                      int32_t downloads,
                                      const char* car_id,
                                      const char* track_id);
void screen_setup_exchange_finish_results(void);
void screen_setup_exchange_apply_search_error(const char* error);
void screen_setup_exchange_apply_download_ack(bool ok,
                                              int32_t setup_id,
                                              const char* name,
                                              const char* path,
                                              const char* error);

typedef enum {
    SE_REQ_NONE = 0,
    SE_REQ_SEARCH,
    SE_REQ_DOWNLOAD,
} se_request_kind_t;

#define SE_TEXT_MAX 80

typedef struct {
    se_request_kind_t kind;
    int32_t           setup_id;
    char              name[SE_TEXT_MAX];
    char              car_id[32];
    char              track_id[32];
    char              search[SE_TEXT_MAX];
} se_request_t;

se_request_t screen_setup_exchange_pop_request(void);
void screen_setup_exchange_set_sidecar_link_up(int link_up);

#ifdef __cplusplus
}
#endif
