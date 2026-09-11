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
 *
 * <p>The PostgreSQL driver is loaded explicitly instead of relying on JDBC
 * auto-discovery. In a servlet container the application classes live in a
 * web-application class loader, while {@link DriverManager} may already have
 * been initialized by a parent class loader. Explicit loading makes the small
 * training WAR reliable across Tomcat and CI environments.</p>
 */
public final class Database {
    private static final String POSTGRES_DRIVER = "org.postgresql.Driver";

    private Database() {
    }

    public static Connection open() throws SQLException {
        ensurePostgresDriverLoaded();

        String host = env("DB_HOST", "postgres");
        String port = env("DB_PORT", "5432");
        String database = env("DB_NAME", "memberdb");
        String user = env("DB_USER", "memberapp");
        String password = env("DB_PASSWORD", "memberapp");
        String url = "jdbc:postgresql://" + host + ":" + port + "/" + database;
        return DriverManager.getConnection(url, user, password);
    }

    /**
     * Registers the PostgreSQL JDBC driver with DriverManager.
     *
     * @throws SQLException when the driver dependency is missing from the WAR
     */
    private static void ensurePostgresDriverLoaded() throws SQLException {
        try {
            Class.forName(POSTGRES_DRIVER);
        } catch (ClassNotFoundException ex) {
            throw new SQLException(
                    "PostgreSQL JDBC driver is not available in the application classpath",
                    ex
            );
        }
    }

    private static String env(String key, String defaultValue) {
        String value = System.getenv(key);
        return value == null || value.isBlank() ? defaultValue : value;
    }
}
