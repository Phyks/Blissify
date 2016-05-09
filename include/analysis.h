#ifndef ANALYSIS_H
#define ANALYSIS_H

#include <sqlite3.h>

/**
 * TODO
 */
int _init_db(char* data_folder, char* db_path);


/**
 * TODO
 */
int _parse_music_helper(
        sqlite3* dbh,
        const char *base_path,
        const char *song_uri);


/**
 * Rescan errored files
 *
 * @param db_path       Path to the db file to use.
 * @param base_path     Root directory of the MPD library.
 * @return	0 on success. Non-zero otherwise.
 */
int _rescan_errored(const char *db_path, const char *base_path);


/**
 * TODO
 */
int _purge_db(const char* db_path);

#endif  // ANALYSIS_H
