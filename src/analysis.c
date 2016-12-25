#include "analysis.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include <bliss.h>

#include "constants.h"
#include "utilities.h"


int _init_db(char *data_folder, char* db_path)
{
	data_folder[0] = '\0';
	db_path[0] = '\0';
    char *xdg_data_home_env = getenv("XDG_DATA_HOME");
    if (NULL == xdg_data_home_env) {
        strncat(data_folder, getenv("HOME"), DEFAULT_STRING_LENGTH);
        strip_trailing_slash(data_folder);
        strncat(data_folder, "/.local/share/blissify", DEFAULT_STRING_LENGTH - strlen(data_folder));
    }
    else {
        strncat(data_folder, xdg_data_home_env, DEFAULT_STRING_LENGTH);
        strip_trailing_slash(data_folder);
        strncat(data_folder, "/blissify", DEFAULT_STRING_LENGTH - strlen(data_folder));
    }

    // Ensure data folder exists
    mkdir(data_folder, 0700);

	// Db path
    strncat(db_path, data_folder, DEFAULT_STRING_LENGTH);
    strncat(db_path, "/db.sqlite3", DEFAULT_STRING_LENGTH - strlen(db_path));

    sqlite3 *dbh;
    if (0 != sqlite3_open_v2(db_path, &dbh, SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE, NULL)) {
        fprintf(stderr, "Unable to open SQLite db.\n");
        return 1;
    }
    int dberr = sqlite3_exec(dbh, "PRAGMA foreign_keys = ON", NULL, NULL, NULL);
    if (SQLITE_OK != dberr) {
        fprintf(stderr, "Error creating db: %s.\n", sqlite3_errmsg(dbh));
        sqlite3_close(dbh);
        return 1;
    }
    dberr = sqlite3_exec(dbh, "CREATE TABLE IF NOT EXISTS songs( \
        id INTEGER PRIMARY KEY, \
        tempo REAL, \
        amplitude REAL, \
        frequency REAL, \
        attack REAL, \
        filename TEXT UNIQUE, \
		album TEXT)",
        NULL, NULL, NULL);
    if (SQLITE_OK != dberr) {
        fprintf(stderr, "Error creating db: %s.\n", sqlite3_errmsg(dbh));
        sqlite3_close(dbh);
        return 1;
    }
    dberr = sqlite3_exec(dbh, "CREATE TABLE IF NOT EXISTS distances( \
        song1 INTEGER, \
        song2 INTEGER, \
        distance REAL, \
        similarity REAL, \
        FOREIGN KEY(song1) REFERENCES songs(id) ON DELETE CASCADE, \
        FOREIGN KEY(song2) REFERENCES songs(id) ON DELETE CASCADE, \
        UNIQUE (song1, song2))",
        NULL, NULL, NULL);
    if (SQLITE_OK != dberr) {
        fprintf(stderr, "Error creating db: %s.\n", sqlite3_errmsg(dbh));
        sqlite3_close(dbh);
        return 1;
    }
    dberr = sqlite3_exec(dbh, "CREATE TABLE IF NOT EXISTS errors( \
        id INTEGER PRIMARY KEY, \
        filename TEXT UNIQUE)", NULL, NULL, NULL);
    if (SQLITE_OK != dberr) {
        fprintf(stderr, "Error creating db: %s.\n", sqlite3_errmsg(dbh));
        sqlite3_close(dbh);
        return 1;
    }
    dberr = sqlite3_exec(dbh, "CREATE TABLE IF NOT EXISTS metadata( \
        name TEXT UNIQUE, \
        value TEXT)", NULL, NULL, NULL);
    if (SQLITE_OK != dberr) {
        fprintf(stderr, "Error creating db: %s.\n", sqlite3_errmsg(dbh));
        sqlite3_close(dbh);
        return 1;
    }
    sqlite3_stmt *res;
    sqlite3_prepare_v2(dbh,
            "INSERT INTO metadata(name, value) VALUES(?, ?)",
            -1, &res, 0);
    sqlite3_bind_text(res, 1, "version", strlen("version"), SQLITE_STATIC);
    sqlite3_bind_text(res, 2, VERSION, strlen(VERSION), SQLITE_STATIC);
    sqlite3_step(res);
    sqlite3_finalize(res);
	sqlite3_close(dbh);
	return 0;
}


int _parse_music_helper(
        sqlite3* dbh,
        const char *base_path,
        const char *song_uri)
{
    sqlite3_stmt *res;

    // Compute full uri
    printf("\nAdding new song to db: %s\n", song_uri);
    char song_full_uri[DEFAULT_STRING_LENGTH + 1] = "";
    strncat(song_full_uri, base_path, DEFAULT_STRING_LENGTH);
    strncat(song_full_uri, song_uri, DEFAULT_STRING_LENGTH - strlen(song_full_uri));

    // Pass it to bliss
    struct bl_song song_analysis;
	bl_initialize_song(&song_analysis);
    if (BL_UNEXPECTED == bl_analyze(song_full_uri, &song_analysis)) {
        fprintf(stderr, "Error while parsing song: %s.\n\n", song_full_uri);
        // Free song analysis
        bl_free_song(&song_analysis);
        // Store error in db
        sqlite3_prepare_v2(dbh,
                "INSERT INTO errors(filename) VALUES(?)",
                -1, &res, 0);
        sqlite3_bind_text(res, 1, song_uri, strlen(song_uri), SQLITE_STATIC);
        sqlite3_step(res);
        sqlite3_finalize(res);
        // Pass file
        return 1;
    }
    // Insert into db
    // Begin transaction
    int dberr = sqlite3_exec(dbh, "BEGIN TRANSACTION", NULL, NULL, NULL);
    if (SQLITE_OK != dberr) {
        fprintf(stderr, "Error while inserting data in db: %s\n\n", sqlite3_errmsg(dbh));
        // Free song analysis
        bl_free_song(&song_analysis);
        sqlite3_exec(dbh, "ROLLBACK", NULL, NULL, NULL);
        // Store error in db
        sqlite3_prepare_v2(dbh,
                "INSERT INTO errors(filename) VALUES(?)",
                -1, &res, 0);
        sqlite3_bind_text(res, 1, song_uri, strlen(song_uri), SQLITE_STATIC);
        sqlite3_step(res);
        sqlite3_finalize(res);
        // Pass file
        return 1;
    }
    // Insert song analysis in database
    dberr = sqlite3_prepare_v2(dbh,
            "INSERT INTO songs(tempo, amplitude, frequency, attack, filename, album) VALUES(?, ?, ?, ?, ?, ?)",
            -1, &res, 0);
    if (SQLITE_OK != dberr) {
        fprintf(stderr, "Error while inserting data in db: %s\n\n", sqlite3_errmsg(dbh));
        // Free song analysis
        bl_free_song(&song_analysis);
        sqlite3_exec(dbh, "ROLLBACK", NULL, NULL, NULL);
        // Store error in db
        sqlite3_prepare_v2(dbh,
                "INSERT INTO errors(filename) VALUES(?)",
                -1, &res, 0);
        sqlite3_bind_text(res, 1, song_uri, strlen(song_uri), SQLITE_STATIC);
        sqlite3_step(res);
        sqlite3_finalize(res);
        // Pass file
        return 1;
    }
    sqlite3_bind_double(res, 1, song_analysis.force_vector.tempo);
    sqlite3_bind_double(res, 2, song_analysis.force_vector.amplitude);
    sqlite3_bind_double(res, 3, song_analysis.force_vector.frequency);
    sqlite3_bind_double(res, 4, song_analysis.force_vector.attack);
    sqlite3_bind_text(res, 5, song_uri, strlen(song_uri), SQLITE_STATIC);
	sqlite3_bind_text(res, 6, song_analysis.album, strlen(song_analysis.album), SQLITE_STATIC);
    dberr = sqlite3_step(res);
    if (SQLITE_DONE != dberr) {
        // Free song analysis
        bl_free_song(&song_analysis);
        sqlite3_exec(dbh, "ROLLBACK", NULL, NULL, NULL);
        // Store error in db
        sqlite3_prepare_v2(dbh,
                "INSERT INTO errors(filename) VALUES(?)",
                -1, &res, 0);
        sqlite3_bind_text(res, 1, song_uri, strlen(song_uri), SQLITE_STATIC);
        sqlite3_step(res);
        sqlite3_finalize(res);
        // Pass file
        return 1;
    }
    sqlite3_finalize(res);
    // Commit transaction
    dberr = sqlite3_exec(dbh, "COMMIT", NULL, NULL, NULL);
    if (SQLITE_OK != dberr) {
        fprintf(stderr, "Error while inserting data in db: %s\n\n", sqlite3_errmsg(dbh));
        // Free song analysis
        bl_free_song(&song_analysis);
        sqlite3_exec(dbh, "ROLLBACK", NULL, NULL, NULL);
        // Store error in db
        sqlite3_prepare_v2(dbh,
                "INSERT INTO errors(filename) VALUES(?)",
                -1, &res, 0);
        sqlite3_bind_text(res, 1, song_uri, strlen(song_uri), SQLITE_STATIC);
        sqlite3_step(res);
        sqlite3_finalize(res);
        // Pass file
        return 1;
    }

    // Free song analysis
    bl_free_song(&song_analysis);

    return 0;
}


int _rescan_errored(const char *db_path, const char *base_path)
{
    // Connect to SQLite db
    sqlite3 *dbh;
    if (0 != sqlite3_open(db_path, &dbh)) {
        fprintf(stderr, "Unable to open SQLite db.\n");
        return 1;
    }

    // Get the list of all the files to process
    sqlite3_stmt *res = NULL;
    int dberr = sqlite3_exec(dbh, "SELECT filename FROM errors", NULL, NULL, NULL);
    if (SQLITE_OK != dberr) {
        fprintf(stderr, "Error while fetching data in db: %s\n\n", sqlite3_errmsg(dbh));
        sqlite3_close(dbh);
        return 1;
    }
    // Handle the files
    while (sqlite3_step(res) == SQLITE_ROW) {
        const char* filename = (char*) sqlite3_column_text(res, 1);

        // Delete it from errors list
        sqlite3_stmt *res2;
        int dberr2 = sqlite3_prepare_v2(dbh,
                "DELETE FROM errors WHERE filename=?",
                -1, &res2, 0);
        if (SQLITE_OK != dberr2) {
            fprintf(stderr, "Error while deleting error from db: %s\n\n", sqlite3_errmsg(dbh));
            continue;
        }
        sqlite3_bind_text(res2, 1, filename, strlen(filename), SQLITE_STATIC);
        sqlite3_step(res2);
        sqlite3_finalize(res2);

        // Try to import it back
        if (1 == _parse_music_helper(dbh, base_path, filename)) {
            continue;
        }
    }
    sqlite3_finalize(res);

    // Close SQLite connection
    sqlite3_close(dbh);

    printf("Done! :)\n");
	return 0;
}


int _purge_db(const char* db_path)
{
    sqlite3 *dbh;
    if (0 != sqlite3_open_v2(db_path, &dbh, SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE, NULL)) {
        fprintf(stderr, "Unable to open SQLite db.\n");
        return 1;
    }
    int dberr = sqlite3_exec(dbh, "PRAGMA foreign_keys = ON", NULL, NULL, NULL);
    if (SQLITE_OK != dberr) {
        fprintf(stderr, "Unable to open SQLite db.\n");
        sqlite3_close(dbh);
        return 1;
    }
	dberr = sqlite3_exec(dbh, "BEGIN TRANSACTION; DELETE FROM distances; DELETE FROM songs; DELETE FROM errors; COMMIT", NULL, NULL, NULL);
	if (SQLITE_OK != dberr) {
		fprintf(stderr, "Error purging existing data in db: %s.\n", sqlite3_errmsg(dbh));
		sqlite3_close(dbh);
		return 1;
	}
    sqlite3_close(dbh);
	return 0;
}
