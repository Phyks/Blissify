cmake_minimum_required (VERSION 2.8)

project (MPDBliss C)

add_subdirectory (bliss)

file (GLOB MPDBLISS_SRC "src/*.c")

# TODO \/
find_package(PkgConfig REQUIRED)
pkg_check_modules(MULTIMEDIA REQUIRED libavformat libavutil libavcodec)
pkg_check_modules(RESAMPLE QUIET libswresample)
if(NOT RESAMPLE_FOUND)
	pkg_check_modules(RESAMPLE REQUIRED libavresample)
	set(AVRESAMPLE TRUE)
else()
	set(AVRESAMPLE FALSE)
endif()
include_directories(${MULTIMEDIA_INCLUDE_DIRS} ${RESAMPLE_INCLUDE_DIRS} include/ bliss/include)
link_directories(${MULTIMEDIA_LIBRARY_DIRS} ${RESAMPLE_LIBRARY_DIRS})
add_definitions(${MULTIMEDIA_CFLAGS_OTHER} ${RESAMPLE_CFLAGS_OTHER})
add_definitions (-Wall -Wno-long-long -pedantic -std=c99)
# TODO /\

add_executable (mpdbliss
    ${MPDBLISS_SRC})

target_link_libraries (mpdbliss
    m
    sqlite3
    mpdclient
    bliss)
