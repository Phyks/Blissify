#include <signal.h>
#include <stdio.h>
#include <stdlib.h>

#include <sqlite3.h>

#include "analysis.h"
#include "constants.h"
#include "utilities.h"

// TODO: Handle deletions from db


int main(int argc, char** argv) {
	if (argc < 3) {
		printf("Usage: %s basepath [relative_filenames].\n", argv[0]);
		return EXIT_SUCCESS;
	}

    // Get data directory, init db file
	char mpdbliss_data_folder[DEFAULT_STRING_LENGTH + 1] = "";
	char mpdbliss_data_db[DEFAULT_STRING_LENGTH + 1] = "";
	if (0 != _init_db(mpdbliss_data_folder, mpdbliss_data_db)) {
		exit(EXIT_FAILURE);
	}

	const char *base_path = argv[1];

    // Connect to SQLite db
    sqlite3 *dbh;
    if (0 != sqlite3_open(mpdbliss_data_db, &dbh)) {
        fprintf(stderr, "Unable to open SQLite db.\n");
		exit(EXIT_FAILURE);
    }
    int dberr = sqlite3_exec(dbh, "PRAGMA foreign_keys = ON", NULL, NULL, NULL);
    if (SQLITE_OK != dberr) {
        fprintf(stderr, "Unable to open SQLite db.\n");
        sqlite3_close(dbh);
		exit(EXIT_FAILURE);
    }

	for (int i = 2; i < argc; ++i) {
		_parse_music_helper(dbh, base_path, argv[i]);
	}

    // Close SQLite connection
    sqlite3_close(dbh);

    printf("Done! :)\n");

    return EXIT_SUCCESS;
}
