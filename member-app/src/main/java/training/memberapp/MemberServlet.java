package training.memberapp;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServlet;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import java.io.IOException;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.logging.Logger;

/**
 * Minimal CRUD servlet used as the system-under-operation in the Agent workshop.
 *
 * <p>The application is intentionally ordinary. The AI portion belongs to the
 * operational Agent, not to this business application.</p>
 */
public class MemberServlet extends HttpServlet {
    private static final Logger LOGGER = Logger.getLogger(MemberServlet.class.getName());
    private static final String AUDIT_LOG_PATH = env("AUDIT_LOG_PATH", "");
    private final ObjectMapper mapper = new ObjectMapper();

    @Override
    protected void service(HttpServletRequest request, HttpServletResponse response)
            throws ServletException, IOException {
        String requestId = UUID.randomUUID().toString();
        request.setAttribute("requestId", requestId);
        response.setHeader("X-Request-ID", requestId);
        long started = System.nanoTime();
        try {
            if (!AUDIT_LOG_PATH.isBlank()) {
                try {
                    appendAuditRecord(requestId, request);
                } catch (IOException ex) {
                    LOGGER.severe("requestId=" + requestId
                            + " audit_write_failed path=" + logValue(AUDIT_LOG_PATH)
                            + " reason=" + logValue(ex.getMessage()));
                    json(response, HttpServletResponse.SC_INTERNAL_SERVER_ERROR,
                            Map.of(
                                    "error", "audit storage unavailable",
                                    "detail", ex.getMessage() == null
                                            ? ex.getClass().getSimpleName()
                                            : ex.getMessage()
                            ));
                    return;
                }
            }

            super.service(request, response);
        } catch (JsonProcessingException ex) {
            LOGGER.warning("requestId=" + requestId + " invalid_json");
            json(response, HttpServletResponse.SC_BAD_REQUEST, Map.of("error", "valid JSON object is required"));
        } catch (IllegalArgumentException ex) {
            LOGGER.warning("requestId=" + requestId + " validation_failed reason=" + ex.getMessage());
            json(response, HttpServletResponse.SC_BAD_REQUEST, Map.of("error", ex.getMessage()));
        } catch (ServletException | IOException | RuntimeException ex) {
            LOGGER.severe("requestId=" + requestId + " unhandled_failure type=" + ex.getClass().getSimpleName());
            if (!response.isCommitted()) {
                response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            }
            throw ex;
        } finally {
            LOGGER.info("requestId=" + requestId + " method=" + logValue(request.getMethod())
                    + " path=" + logValue(request.getRequestURI())
                    + " contentType=" + logValue(request.getContentType())
                    + " status=" + response.getStatus()
                    + " durationMs=" + (System.nanoTime() - started) / 1_000_000);
        }
    }

    private void appendAuditRecord(String requestId, HttpServletRequest request) throws IOException {
        Path path = Path.of(AUDIT_LOG_PATH);
        Path parent = path.getParent();
        if (parent != null) {
            Files.createDirectories(parent);
        }

        String record = "requestId=" + requestId
                + " method=" + logValue(request.getMethod())
                + " path=" + logValue(request.getRequestURI())
                + System.lineSeparator();

        Files.writeString(
                path,
                record,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE,
                StandardOpenOption.WRITE,
                StandardOpenOption.APPEND
        );
    }

    private String logValue(String value) {
        if (value == null) {
            return "none";
        }
        return value.replaceAll("[\\r\\n\\t]", "_").substring(0, Math.min(value.length(), 200));
    }

    @Override
    protected void doGet(HttpServletRequest request, HttpServletResponse response) throws IOException {
        String name = request.getParameter("name");
        String sql = name == null || name.isBlank()
                ? "SELECT id, name, department, email FROM members ORDER BY id"
                : "SELECT id, name, department, email FROM members WHERE name ILIKE ? ORDER BY id";

        try (Connection connection = Database.open();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            if (name != null && !name.isBlank()) {
                statement.setString(1, "%" + name + "%");
            }

            List<Map<String, Object>> members = new ArrayList<>();
            try (ResultSet rs = statement.executeQuery()) {
                while (rs.next()) {
                    members.add(member(rs));
                }
            }
            json(response, HttpServletResponse.SC_OK, members);
        } catch (SQLException ex) {
            databaseFailure("GET", ex, response);
        }
    }

    @Override
    protected void doPost(HttpServletRequest request, HttpServletResponse response) throws IOException {
        Map<String, String> body = readMember(request);
        String sql = "INSERT INTO members(name, department, email) VALUES (?, ?, ?) RETURNING id";

        try (Connection connection = Database.open();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, body.get("name"));
            statement.setString(2, body.get("department"));
            statement.setString(3, body.get("email"));
            try (ResultSet rs = statement.executeQuery()) {
                rs.next();
                json(response, HttpServletResponse.SC_CREATED, Map.of("id", rs.getLong(1)));
            }
        } catch (SQLException ex) {
            databaseFailure("POST", ex, response);
        }
    }

    @Override
    protected void doPut(HttpServletRequest request, HttpServletResponse response) throws IOException {
        long id = idFromPath(request);
        Map<String, String> body = readMember(request);
        String sql = "UPDATE members SET name=?, department=?, email=? WHERE id=?";

        try (Connection connection = Database.open();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, body.get("name"));
            statement.setString(2, body.get("department"));
            statement.setString(3, body.get("email"));
            statement.setLong(4, id);
            int count = statement.executeUpdate();
            if (count == 0) {
                json(response, HttpServletResponse.SC_NOT_FOUND, Map.of("error", "member not found"));
                return;
            }
            json(response, HttpServletResponse.SC_OK, Map.of("updated", id));
        } catch (SQLException ex) {
            databaseFailure("PUT", ex, response);
        }
    }

    @Override
    protected void doDelete(HttpServletRequest request, HttpServletResponse response) throws IOException {
        long id = idFromPath(request);
        try (Connection connection = Database.open();
             PreparedStatement statement = connection.prepareStatement("DELETE FROM members WHERE id=?")) {
            statement.setLong(1, id);
            int count = statement.executeUpdate();
            if (count == 0) {
                json(response, HttpServletResponse.SC_NOT_FOUND, Map.of("error", "member not found"));
                return;
            }
            json(response, HttpServletResponse.SC_OK, Map.of("deleted", id));
        } catch (SQLException ex) {
            databaseFailure("DELETE", ex, response);
        }
    }

    private long idFromPath(HttpServletRequest request) {
        String path = request.getPathInfo();
        if (path == null || path.equals("/") || path.length() < 2) {
            throw new IllegalArgumentException("member id is required in path");
        }
        try {
            long id = Long.parseLong(path.substring(1));
            if (id <= 0) {
                throw new NumberFormatException();
            }
            return id;
        } catch (NumberFormatException ex) {
            throw new IllegalArgumentException("member id must be a positive integer");
        }
    }

    private Map<String, String> readMember(HttpServletRequest request) throws IOException {
        Map<?, ?> body = mapper.readValue(request.getInputStream(), Map.class);
        if (body == null) {
            throw new IllegalArgumentException("valid JSON object is required");
        }
        LOGGER.info("requestId=" + request.getAttribute("requestId") + " member_payload"
                + " name=" + fieldState(body.get("name"))
                + " department=" + fieldState(body.get("department"))
                + " email=" + fieldState(body.get("email")));
        // Validate before opening a database connection.
        return Map.of("name", required(body, "name"),
                "department", required(body, "department"), "email", required(body, "email"));
    }

    private String fieldState(Object value) {
        if (value == null) {
            return "missing_or_null";
        }
        if (!(value instanceof String)) {
            return "invalid_type";
        }
        return ((String) value).isBlank() ? "blank" : "present";
    }

    private String required(Map<?, ?> body, String key) {
        Object value = body.get(key);
        if (value == null || value.toString().isBlank()) {
            throw new IllegalArgumentException(key + " is required");
        }
        if (!(value instanceof String)) {
            throw new IllegalArgumentException(key + " must be a string");
        }
        return value.toString();
    }

    private Map<String, Object> member(ResultSet rs) throws SQLException {
        Map<String, Object> result = new HashMap<>();
        result.put("id", rs.getLong("id"));
        result.put("name", rs.getString("name"));
        result.put("department", rs.getString("department"));
        result.put("email", rs.getString("email"));
        return result;
    }

    private void databaseFailure(String operation, SQLException ex, HttpServletResponse response) throws IOException {
        LOGGER.severe("requestId=" + response.getHeader("X-Request-ID")
                + " database_failure operation=" + operation + " sqlState=" + ex.getSQLState()
                + " errorCode=" + ex.getErrorCode());
        json(response, HttpServletResponse.SC_INTERNAL_SERVER_ERROR,
                Map.of("error", "database operation failed", "detail", ex.getMessage()));
    }

    private static String env(String key, String defaultValue) {
        String value = System.getenv(key);
        return value == null || value.isBlank() ? defaultValue : value;
    }

    private void json(HttpServletResponse response, int status, Object value) throws IOException {
        response.setStatus(status);
        response.setContentType("application/json");
        response.setCharacterEncoding("UTF-8");
        try (PrintWriter writer = response.getWriter()) {
            mapper.writeValue(writer, value);
        }
    }
}
