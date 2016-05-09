#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <mpd/client.h>
#include <sqlite3.h>

#include "analysis.h"
#include "cmdline.h"
#include "utilities.h"

// TODO: Handle deletions from db

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
 * Update the database.
 *
 * @param mpd_connection    MPD connection object to use.
 * @param initial_mtime     Initial mtime to use.
 * @param mpd_base_path     Root directory of the MPD library.
 * @param mpdbliss_data_db	Path to the db to use.
 */
long int  update_database(
        time_t initial_mtime,
        const char *mpd_base_path,
		const char* mpdbliss_data_db
    )
{
    // Store latest mtime seen
    time_t latest_mtime = initial_mtime;

    // Get number of songs in db
    struct mpd_stats* stats = mpd_run_stats(conn);
    if (NULL == stats) {
        fprintf(stderr, "Unable to fetch number of songs in the db.\n");
        return -1;
    }
    unsigned int n_songs = mpd_stats_get_number_of_songs(stats);
    if (0 == n_songs) {
        fprintf(stderr, "Unable to fetch number of songs in the db.\n");
        return -1;
    }

    // Get the list of all the files to process
    if (!mpd_send_list_all_meta(conn, NULL)) {
        fprintf(stderr, "Unable to get a full list of items in the db.\n");
        return -1;
    }

    // Connect to SQLite db
    sqlite3 *dbh;
    if (0 != sqlite3_open(mpdbliss_data_db, &dbh)) {
        fprintf(stderr, "Unable to open SQLite db.\n");
        return -1;
    }

    // Retrieve the received list in memory, to prevent timeout
    struct mpd_entity **entities = malloc(sizeof(struct mpd_entity *) * n_songs);
    struct mpd_entity *entity;
    int i = 0;
    while ((entity = mpd_recv_entity(conn)) != NULL) {
        switch (mpd_entity_get_type(entity)) {
            case MPD_ENTITY_TYPE_SONG:
                entities[i] = entity;
                break;

            case MPD_ENTITY_TYPE_UNKNOWN:
            case MPD_ENTITY_TYPE_DIRECTORY:
            case MPD_ENTITY_TYPE_PLAYLIST:
                // Pass such types
                mpd_entity_free(entity);
                continue;
        }
        ++i;
    }

    // Process all the entities
    for (int i = 0; i < n_songs; ++i) {
        struct mpd_entity *entity = entities[i];
        const struct mpd_song *song = mpd_entity_get_song(entity);

        // Pass song if already seen
        time_t song_mtime = mpd_song_get_last_modified(song);
        if (difftime(song_mtime, initial_mtime) <= 0) {
            mpd_entity_free(entity);
            continue;
        }

        // Compute bl_analyze and store it
        const char *song_uri = mpd_song_get_uri(song);
        if (1 == _parse_music_helper(dbh, mpd_base_path, song_uri)) {
            mpd_entity_free(entity);
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

    // Check if exit was due to an error
    if (mpd_connection_get_error(conn) != MPD_ERROR_SUCCESS) {
        printf("MPD Error: %s\n", mpd_connection_get_error_message(conn));
        return -1;
    }

    free(entities);
    printf("Done! :)\n");

    // Return last_mtime, if no error occured.
	return latest_mtime;
}


int main(int argc, char** argv) {
    // Scan arguments
	struct gengetopt_args_info args_info;
    if (0 != cmdline_parser(argc, argv, &args_info)) {
        exit(EXIT_FAILURE) ;
    }

    // Create MPD connection
    char *mpd_host = NULL;
    if (strlen(args_info.host_arg) > 0) {
        mpd_host = args_info.host_arg;
    }
    struct mpd_settings* conn_settings = mpd_settings_new(
            mpd_host,
            args_info.port_arg,
            0,
            NULL,
            NULL);
    // Connect
    conn = mpd_connection_new(
            mpd_settings_get_host(conn_settings),
            mpd_settings_get_port(conn_settings),
            mpd_settings_get_timeout_ms(conn_settings));
    if (mpd_connection_get_error(conn) != MPD_ERROR_SUCCESS) {
        fprintf(stderr, "Unable to connect to the MPD server.\n");
        exit(EXIT_FAILURE);
    }
    // Handle passwords
    const char* mpd_password = mpd_settings_get_password(conn_settings);
    if (NULL != mpd_password) {
        if (!mpd_run_password(conn, mpd_password)) {
            fprintf(stderr, "Unable to send password to the MPD server.\n");
            exit(EXIT_FAILURE);
        }
    }

    // Handle mpd_root argument
    char mpd_base_path[DEFAULT_STRING_LENGTH] = "";
    strncat(mpd_base_path, args_info.mpd_root_arg, DEFAULT_STRING_LENGTH);
    strip_trailing_slash(mpd_base_path);
    strncat(mpd_base_path, "/", DEFAULT_STRING_LENGTH - strlen(mpd_base_path));

    // Get data directory, init db file
	char mpdbliss_data_folder[DEFAULT_STRING_LENGTH] = "";
	char mpdbliss_data_db[DEFAULT_STRING_LENGTH] = "";
	if (0 != _init_db(mpdbliss_data_folder, mpdbliss_data_db)) {
		exit(EXIT_FAILURE);
	}

    // Set data file path
	char mpdbliss_data_file[DEFAULT_STRING_LENGTH] = "";
    strncat(mpdbliss_data_file, mpdbliss_data_folder, DEFAULT_STRING_LENGTH);
    strncat(mpdbliss_data_file, "/latest_mtime.txt", DEFAULT_STRING_LENGTH - strlen(mpdbliss_data_file));

    // Get latest mtime
    time_t last_mtime = 0;  // Set it to epoch by default
    FILE *fp = fopen(mpdbliss_data_file, "r");
    if (NULL != fp) {
        // Read it from file if applicable
        fscanf(fp, "%ld\n", &last_mtime);
        fclose(fp);
    }

    // Purge db if a rescan is needed
    if (1 == args_info.rescan_flag) {
		if (0 != _purge_db(mpdbliss_data_db)) {
			exit(EXIT_FAILURE);
		}
        // Set last_mtime to 0
        last_mtime = 0;
    }

    // Check if a full rescan is needed
    if (1 == args_info.rescan_flag) {
        last_mtime = update_database(last_mtime, mpd_base_path, mpdbliss_data_db);
		if (last_mtime < 0) {
            fprintf(stderr, "An error occurred while scanning library.\n");
            exit(EXIT_FAILURE);
		}
	}
    // Else, if we want to rescan errored files
    else if (1 == args_info.rescan_errors_flag) {
		// Update last_mtime
        _rescan_errored(mpdbliss_data_db, mpd_base_path);
    }
    // Else, if we requested an update of the db
    else if (true == args_info.update_flag) {
        // Rescan from last known mtime
        last_mtime = update_database(last_mtime, mpd_base_path, mpdbliss_data_db);
		if (last_mtime < 0) {
            fprintf(stderr, "An error occurred while scanning library.\n");
            exit(EXIT_FAILURE);
		}
    }
    else {
        // Setting signal handler
        if (signal(SIGINT, sigint_catch_function) == SIG_ERR) {
            fprintf(stderr, "An error occurred while setting a signal handler.\n");
            exit(EXIT_FAILURE);
        }

        while (mpd_run_idle_loop) {
            // Else, start an MPD IDLE connection
            mpd_run_idle_mask(conn, MPD_IDLE_DATABASE);

            // Rescan from last known mtime
            last_mtime = update_database(last_mtime, mpd_base_path, mpdbliss_data_db);
			if (last_mtime < 0) {
				fprintf(stderr, "An error occurred while scanning library.\n");
				exit(EXIT_FAILURE);
			}

            // Stop listening to MPD IDLE
            mpd_run_noidle(conn);
        }
    }

	// Write last_mtime
	fp = fopen(mpdbliss_data_file, "w+");
	if (NULL != fp) {
		fprintf(fp, "%ld\n", last_mtime);
		fclose(fp);
	}
	else {
		fprintf(stderr, "Unable to store latest mtime seen.\n");
		exit(EXIT_FAILURE);
	}

    return EXIT_SUCCESS;
}
