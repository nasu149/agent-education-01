package training.memberapp;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;

/**
 * Creates PostgreSQL connections from environment variables.
 *
 * <p>This intentionally avoids a connection pool so that the training
 * environment stays small and failures such as a changed database password
 * become visible immediately on the next request.</p>
 */
public final class Database {
    private Database() {
    }

    public static Connection open() throws SQLException {
        String host = env("DB_HOST", "postgres");
        String port = env("DB_PORT", "5432");
        String database = env("DB_NAME", "memberdb");
        String user = env("DB_USER", "memberapp");
        String password = env("DB_PASSWORD", "memberapp");
        String url = "jdbc:postgresql://" + host + ":" + port + "/" + database;
        return DriverManager.getConnection(url, user, password);
    }

    private static String env(String key, String defaultValue) {
        String value = System.getenv(key);
        return value == null || value.isBlank() ? defaultValue : value;
    }
}
