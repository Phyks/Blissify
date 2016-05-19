cmake_minimum_required (VERSION 2.8)

project (MPDBliss C)

add_subdirectory (bliss)

file (GLOB COMMON_SRC "src/*.c")

find_package(PkgConfig REQUIRED)
pkg_check_modules(MULTIMEDIA REQUIRED libavformat libavutil libavcodec)
include_directories(${MULTIMEDIA_INCLUDE_DIRS} include/ bliss/include)
link_directories(${MULTIMEDIA_LIBRARY_DIRS})
add_definitions(${MULTIMEDIA_CFLAGS_OTHER})
add_definitions (-Wall -Wno-long-long -pedantic -std=c99)

add_executable (mpdbliss
	${COMMON_SRC} "main_mpd.c")

target_link_libraries (mpdbliss
    m
    sqlite3
    mpdclient
    bliss)


add_executable (argsbliss
	${COMMON_SRC} "main_args.c")

target_link_libraries (argsbliss
    m
    sqlite3
    bliss)
