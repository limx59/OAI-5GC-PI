# Included from FlexRIC's C xApp examples when lab demos are enabled.
add_executable(xapp_handover_control
    xapp_handover_control.c
    ${CMAKE_SOURCE_DIR}/src/util/alg_ds/alg/defer.c
)

target_link_libraries(xapp_handover_control
    PRIVATE
    e42_xapp
    $<TARGET_OBJECTS:e2_time_obj>
    $<$<STREQUAL:${XAPP_DB},MYSQL_XAPP>:${LIBMYSQLCLIENT_LIBRARIES}>
    -pthread
    -lsctp
    -ldl
)
