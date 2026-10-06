add_subdirectory(helloworld)
add_subdirectory(monitor)
add_subdirectory(control)
add_subdirectory(mwc2024)

option(BUILD_OAI_PI_XAPP_DEMOS "Build project-local xApp lab demos" OFF)
if(BUILD_OAI_PI_XAPP_DEMOS)
    add_subdirectory(
        "${CMAKE_CURRENT_SOURCE_DIR}/../../../../test/xapp"
        "${CMAKE_BINARY_DIR}/oai-pi-xapp"
    )
endif()
