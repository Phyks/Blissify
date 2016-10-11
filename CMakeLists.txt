cmake_minimum_required (VERSION 2.8)

project (Blissify C)

add_subdirectory (bliss)

file (GLOB COMMON_SRC "src/*.c")

find_package(PkgConfig REQUIRED)
pkg_check_modules(MULTIMEDIA REQUIRED libavformat libavutil libavcodec fftw3)
include_directories(${MULTIMEDIA_INCLUDE_DIRS} include/ bliss/include)
link_directories(${MULTIMEDIA_LIBRARY_DIRS})
add_definitions(${MULTIMEDIA_CFLAGS_OTHER})
add_definitions (-Wall -Wno-long-long -pedantic -std=c99)

add_executable (blissify
	${COMMON_SRC})

target_link_libraries (blissify
    m
    sqlite3
    fftw3
    bliss)

install (TARGETS blissify DESTINATION /usr/bin)
