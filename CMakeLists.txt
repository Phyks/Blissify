cmake_minimum_required(VERSION 2.8)

project(MPDBliss C)

add_subdirectory(bliss)

file (GLOB MPDBLISS_SRC "src/*.c")
include_directories("include/" "bliss/include")

add_executable (mpdbliss
    ${MPDBLISS_SRC})

target_link_libraries (mpdbliss
    m
    sqlite3
    mpdclient
    bliss)
