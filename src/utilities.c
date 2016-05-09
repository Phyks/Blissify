#include <stdlib.h>
#include <string.h>

#include "utilities.h"


void strip_trailing_slash(char* str)
{
    size_t length = strlen(str);
    if ('/' == str[length - 1]) {
        str[length - 1] = '\0';
    }
}
