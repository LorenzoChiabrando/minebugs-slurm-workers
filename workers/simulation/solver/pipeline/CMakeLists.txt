cmake_minimum_required(VERSION 3.16)
project(MinebugsSolver VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -DNDEBUG")

# --- Sources ---
file(GLOB_RECURSE SOURCES "src/*.cpp")

# --- Executable ---
add_executable(solver_cpp ${SOURCES})

# --- INCLUDE PATHS ---
target_include_directories(solver_cpp PRIVATE "/usr/local/include/highs" "/usr/local/include")
target_include_directories(solver_cpp PRIVATE include)

# --- LIBRARY LINKING  ---
find_library(HIGHS_LIB NAMES highs libhighs PATHS "/usr/local/lib" NO_DEFAULT_PATH)

if(HIGHS_LIB)
    message(STATUS "Using Custom HiGHS Lib: ${HIGHS_LIB}")
    target_link_libraries(solver_cpp PRIVATE ${HIGHS_LIB})
else()
    message(WARNING "Custom HiGHS lib not found in /usr/local/lib, searching system...")
    find_package(highs CONFIG REQUIRED)
    target_link_libraries(solver_cpp PRIVATE highs::highs)
endif()

# --- Install ---
install(TARGETS solver_cpp DESTINATION bin)
