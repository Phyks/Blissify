#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>

#include <mpd/client.h>
#include <sqlite3.h>

#include "bliss.h"
#include "cmdline.h"

// TODO: Handle deletions from db

#define DEFAULT_STRING_LENGTH 255

// Data file path to store latest seen mtimes and db
char mpdbliss_data_file[DEFAULT_STRING_LENGTH] = "";
char mpdbliss_data_db[DEFAULT_STRING_LENGTH] = "";
// IDLE loop control variable
volatile bool mpd_run_idle_loop = true;
// MPD connection handler
struct mpd_connection *conn;


/**
 * Handle interruption when waiting for MPD IDLE items.
 */
void sigint_catch_function(int signo)
{
    // TODO: Not working
    // TODO: Should store latest seen mtime there
    printf("Exiting...\n");

    // Stop listening for MPD IDLE
    mpd_run_noidle(conn);

    // Stop main loop
    mpd_run_idle_loop = false;
}


/**
 * Strip the trailing slash from a string.
 *
 * @param[in] str   String to strip slash from.
 * @param[out] str   Stripped string.
 */
void strip_trailing_slash(char* str)
{
    size_t length = strlen(str);
    if ('/' == str[length - 1]) {
        str[length - 1] = '\0';
    }
}


/**
 * Update the database.
 *
 * @param mpd_connection    MPD connection object to use.
 * @param initial_mtime     Initial mtime to use.
 * @param mpd_base_path     Root directory of the MPD library.
 */
void update_database(
        struct mpd_connection *conn,
        time_t initial_mtime,
        char *mpd_base_path
    )
{
    // Store latest mtime seen
    time_t latest_mtime = initial_mtime;

    // Get the list of all the files to process
    if (!mpd_send_list_all_meta(conn, NULL)) {
        fprintf(stderr, "Unable to get a full list of items in the db.\n");
        return;
    }

    // Connect to SQLite db
    sqlite3 *dbh;
    if (0 != sqlite3_open(mpdbliss_data_db, &dbh)) {
        fprintf(stderr, "Unable to open SQLite db.\n");
        return;
    }

    // Process the received list
    struct mpd_entity *entity;
    while ((entity = mpd_recv_entity(conn)) != NULL) {
        const struct mpd_song *song;

        switch (mpd_entity_get_type(entity)) {
            case MPD_ENTITY_TYPE_SONG:
                song = mpd_entity_get_song(entity);
                break;

            case MPD_ENTITY_TYPE_UNKNOWN:
            case MPD_ENTITY_TYPE_DIRECTORY:
            case MPD_ENTITY_TYPE_PLAYLIST:
                // Pass such types
                continue;
        }

        // Pass song if already seen
        time_t song_mtime = mpd_song_get_last_modified(song);
        if (difftime(song_mtime, initial_mtime) <= 0) {
            continue;
        }

        // Compute bl_analyze and store it
        const char *song_uri = mpd_song_get_uri(song);
        printf("\nAdding new song to db: %s\n", song_uri);
        struct bl_song song_analysis;
        char song_full_uri[DEFAULT_STRING_LENGTH] = "";
        strncat(song_full_uri, mpd_base_path, DEFAULT_STRING_LENGTH);
        strncat(song_full_uri, song_uri, DEFAULT_STRING_LENGTH);
        if (BL_UNEXPECTED == bl_analyze(song_full_uri, &song_analysis)) {
            fprintf(stderr, "Error while parsing song: %s.\n\n", song_uri);
            continue;
        }
        // Insert into db
        sqlite3_stmt *res;
        // Begin transaction
        int dberr = sqlite3_exec(dbh, "BEGIN TRANSACTION", NULL, NULL, NULL);
        if (SQLITE_OK != dberr) {
            fprintf(stderr, "Error while inserting data in db: %s\n\n", sqlite3_errmsg(dbh));
            sqlite3_exec(dbh, "ROLLBACK", NULL, NULL, NULL);
            continue;
        }
        // Insert song analysis in database
        dberr = sqlite3_prepare_v2(dbh,
                "INSERT INTO songs(tempo, amplitude, frequency, attack, filename) VALUES(?, ?, ?, ?, ?)",
                -1, &res, 0);
        if (SQLITE_OK != dberr) {
            fprintf(stderr, "Error while inserting data in db: %s\n\n", sqlite3_errmsg(dbh));
            sqlite3_exec(dbh, "ROLLBACK", NULL, NULL, NULL);
            continue;
        }
        sqlite3_bind_double(res, 1, song_analysis.force_vector.tempo);
        sqlite3_bind_double(res, 2, song_analysis.force_vector.amplitude);
        sqlite3_bind_double(res, 3, song_analysis.force_vector.frequency);
        sqlite3_bind_double(res, 4, song_analysis.force_vector.attack);
        sqlite3_bind_text(res, 5, song_uri, strlen(song_uri), SQLITE_STATIC);
        sqlite3_step(res);
        sqlite3_finalize(res);
        int last_id = sqlite3_last_insert_rowid(dbh);
        // Insert updated distances
        dberr = sqlite3_prepare_v2(dbh, "SELECT id, tempo, amplitude, frequency, attack FROM songs", -1, &res, 0);
        if (SQLITE_OK != dberr) {
            fprintf(stderr, "Error while inserting data in db: %s\n\n", sqlite3_errmsg(dbh));
            sqlite3_exec(dbh, "ROLLBACK", NULL, NULL, NULL);
            continue;
        }
        int dberr2 = SQLITE_OK;
        while (sqlite3_step(res) == SQLITE_ROW) {
            int id = sqlite3_column_int(res, 0);
            if (id == last_id) {
                // Skip last inserted item
                continue;
            }
            struct force_vector_s song_db;
            song_db.tempo = sqlite3_column_double(res, 1);
            song_db.amplitude = sqlite3_column_double(res, 2);
            song_db.frequency = sqlite3_column_double(res, 3);
            song_db.attack = sqlite3_column_double(res, 4);
            float distance = bl_distance(song_analysis.force_vector, song_db);

            sqlite3_stmt *res2;
            dberr2 = sqlite3_prepare_v2(dbh,
                    "INSERT INTO distances(song1, song2, distance) VALUES(?, ?, ?)",
                    -1, &res2, 0);
            if (SQLITE_OK != dberr2) {
                fprintf(stderr, "Error while inserting data in db: %s\n\n", sqlite3_errmsg(dbh));
                break;
            }
            printf("%d %d %f\n", last_id, id, distance);
            sqlite3_bind_int(res2, 1, last_id);
            sqlite3_bind_int(res2, 2, id);
            sqlite3_bind_double(res2, 3, distance);
            sqlite3_step(res2);
            sqlite3_finalize(res2);
        }
        if (SQLITE_OK != dberr2) {
            sqlite3_exec(dbh, "ROLLBACK", NULL, NULL, NULL);
            continue;
        }
        sqlite3_finalize(res);
        // Commit transaction
        dberr = sqlite3_exec(dbh, "COMMIT", NULL, NULL, NULL);
        if (SQLITE_OK != dberr) {
            fprintf(stderr, "Error while inserting data in db: %s\n\n", sqlite3_errmsg(dbh));
            sqlite3_exec(dbh, "ROLLBACK", NULL, NULL, NULL);
            continue;
        }

        // Update latest mtime
        if (difftime(song_mtime, latest_mtime) >= 0) {
            latest_mtime = song_mtime;
        }

        // Free the allocated entity
        mpd_entity_free(entity);
        printf("\n");
    }

    // Close SQLite connection
    sqlite3_close(dbh);

    // Update last_mtime
    FILE *fp = fopen(mpdbliss_data_file, "w+");
    if (NULL != fp) {
        fprintf(fp, "%d\n", latest_mtime);
        fclose(fp);
    }
    else {
        fprintf(stderr, "Unable to store latest mtime seen.\n");
        return;
    }
}


int main(int argc, char** argv) {
    struct gengetopt_args_info args_info;

    // Scan arguments
    if (0 != cmdline_parser(argc, argv, &args_info)) {
        exit(EXIT_FAILURE) ;
    }

    // Create MPD connection
    conn = mpd_connection_new(
            args_info.host_arg,
            args_info.port_arg,
            30000);
    if (mpd_connection_get_error(conn) != MPD_ERROR_SUCCESS) {
        fprintf(stderr, "Unable to connect to the MPD server.\n");
        exit(EXIT_FAILURE);
    }

    char *mpd_base_path = args_info.mpd_root_arg;

    // Get data directory
    char *xdg_data_home_env = getenv("XDG_DATA_HOME");
    if (NULL == xdg_data_home_env) {
        strncat(mpdbliss_data_file, getenv("HOME"), DEFAULT_STRING_LENGTH);
        strip_trailing_slash(mpdbliss_data_file);
        strncat(mpdbliss_data_file, "/.local/share/mpdbliss", DEFAULT_STRING_LENGTH);
    }
    else {
        strncpy(mpdbliss_data_file, xdg_data_home_env, DEFAULT_STRING_LENGTH);
        strip_trailing_slash(mpdbliss_data_file);
        strncat(mpdbliss_data_file, "/mpdbliss", DEFAULT_STRING_LENGTH);
    }

    // Ensure data folder exists
    mkdir(mpdbliss_data_file, 0700);

    // Set data file path
    strncat(mpdbliss_data_db, mpdbliss_data_file, DEFAULT_STRING_LENGTH);
    strncat(mpdbliss_data_db, "/db.sqlite3", DEFAULT_STRING_LENGTH);
    strncat(mpdbliss_data_file, "/latest_mtime.txt", DEFAULT_STRING_LENGTH);

    // Get latest mtime
    time_t last_mtime = 0;  // Set it to epoch by default
    FILE *fp = fopen(mpdbliss_data_file, "r");
    if (NULL != fp) {
        // Read it from file if applicable
        fscanf(fp, "%d\n", &last_mtime);
        fclose(fp);
    }

    // Initialize database table
    sqlite3 *dbh;
    if (0 != sqlite3_open_v2(mpdbliss_data_db, &dbh, SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE, NULL)) {
        fprintf(stderr, "Unable to open SQLite db.\n");
        return EXIT_FAILURE;
    }
    int dberr = sqlite3_exec(dbh, "PRAGMA foreign_keys = ON", NULL, NULL, NULL);
    if (SQLITE_OK != dberr) {
        fprintf(stderr, "Error creating db: %s.\n", sqlite3_errmsg(dbh));
        sqlite3_close(dbh);
        return EXIT_FAILURE;
    }
    dberr = sqlite3_exec(dbh, "CREATE TABLE IF NOT EXISTS songs( \
        id INTEGER PRIMARY KEY, \
        tempo REAL, \
        amplitude REAL, \
        frequency REAL, \
        attack REAL, \
        filename TEXT)",
        NULL, NULL, NULL);
    if (SQLITE_OK != dberr) {
        fprintf(stderr, "Error creating db: %s.\n", sqlite3_errmsg(dbh));
        sqlite3_close(dbh);
        return EXIT_FAILURE;
    }
    dberr = sqlite3_exec(dbh, "CREATE TABLE IF NOT EXISTS distances( \
        song1 INTEGER, \
        song2 INTEGER, \
        distance REAL, \
        FOREIGN KEY(song1) REFERENCES songs(id) ON DELETE CASCADE, \
        FOREIGN KEY(song2) REFERENCES songs(id) ON DELETE CASCADE)",
        NULL, NULL, NULL);
    if (SQLITE_OK != dberr) {
        fprintf(stderr, "Error creating db: %s.\n", sqlite3_errmsg(dbh));
        sqlite3_close(dbh);
        return EXIT_FAILURE;
    }
    sqlite3_close(dbh);

    // Check if a full rescan is needed
    if (1 == args_info.rescan_flag) {
        update_database(conn, last_mtime, mpd_base_path);
    }
    // Else, if we requested an update of the db
    else if (true == args_info.update_flag) {
        // Rescan from last known mtime
        update_database(conn, last_mtime, mpd_base_path);
    }
    else {
        // Setting signal handler
        if (signal(SIGINT, sigint_catch_function) == SIG_ERR) {
            fprintf(stderr, "An error occurred while setting a signal handler.\n");
            return EXIT_FAILURE;
        }

        while (mpd_run_idle_loop) {
            // Else, start an MPD IDLE connection
            mpd_run_idle_mask(conn, MPD_IDLE_DATABASE);

            // Rescan from last known mtime
            update_database(conn, last_mtime, mpd_base_path);

            // Stop listening to MPD IDLE
            mpd_run_noidle(conn);
        }
    }

    return EXIT_SUCCESS;
}
