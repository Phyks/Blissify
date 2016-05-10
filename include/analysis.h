#ifndef ANALYSIS_H
#define ANALYSIS_H

#include <sqlite3.h>

/**
 * Initialize the SQLite3 database used to store songs data and distances.
 *
 * @param[out] data_folder  Folder in which the data will be
 *                          stored.
 * @param[out] db_path      Full path to the database.
 *
 * @return 0 on success. Non-zero otherwise.
 */
int _init_db(char* data_folder, char* db_path);


/**
 * Analyze a song and store result in database.
 *
 * @param[in] dbh   SQLite3 database handler.
 * @param[in] base_path     Base path of your music library.
 * @param[in] song_uri      Relative path of the song to
 *                          analyze, from the base_path.
 *
 * @return 0 on success. Non-zero otherwise.
 */
int _parse_music_helper(
        sqlite3* dbh,
        const char *base_path,
        const char *song_uri);


/**
 * Rescan errored files
 *
 * @param[in] db_path       Path to the db file to use.
 * @param[in] base_path     Root directory of the MPD library.
 *
 * @return	0 on success. Non-zero otherwise.
 */
int _rescan_errored(const char *db_path, const char *base_path);


/**
 * Purge everything from the database.
 *
 * @param[in] db_path   Path to the db file to use.
 *
 * @return 0 on success. Non-zero otherwise.
 */
int _purge_db(const char* db_path);

#endif  // ANALYSIS_H
