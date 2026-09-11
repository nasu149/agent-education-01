package training.memberapp;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServlet;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import java.io.IOException;
import java.io.PrintWriter;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Minimal CRUD servlet used as the system-under-operation in the Agent workshop.
 *
 * <p>The application is intentionally ordinary. The AI portion belongs to the
 * operational Agent, not to this business application.</p>
 */
public class MemberServlet extends HttpServlet {
    private final ObjectMapper mapper = new ObjectMapper();

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
        Map<?, ?> body = mapper.readValue(request.getInputStream(), Map.class);
        String sql = "INSERT INTO members(name, department, email) VALUES (?, ?, ?) RETURNING id";

        try (Connection connection = Database.open();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, required(body, "name"));
            statement.setString(2, required(body, "department"));
            statement.setString(3, required(body, "email"));
            try (ResultSet rs = statement.executeQuery()) {
                rs.next();
                json(response, HttpServletResponse.SC_CREATED, Map.of("id", rs.getLong(1)));
            }
        } catch (IllegalArgumentException ex) {
            json(response, HttpServletResponse.SC_BAD_REQUEST, Map.of("error", ex.getMessage()));
        } catch (SQLException ex) {
            databaseFailure("POST", ex, response);
        }
    }

    @Override
    protected void doPut(HttpServletRequest request, HttpServletResponse response) throws IOException {
        long id = idFromPath(request);
        Map<?, ?> body = mapper.readValue(request.getInputStream(), Map.class);
        String sql = "UPDATE members SET name=?, department=?, email=? WHERE id=?";

        try (Connection connection = Database.open();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, required(body, "name"));
            statement.setString(2, required(body, "department"));
            statement.setString(3, required(body, "email"));
            statement.setLong(4, id);
            int count = statement.executeUpdate();
            if (count == 0) {
                json(response, HttpServletResponse.SC_NOT_FOUND, Map.of("error", "member not found"));
                return;
            }
            json(response, HttpServletResponse.SC_OK, Map.of("updated", id));
        } catch (IllegalArgumentException ex) {
            json(response, HttpServletResponse.SC_BAD_REQUEST, Map.of("error", ex.getMessage()));
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
        return Long.parseLong(path.substring(1));
    }

    private String required(Map<?, ?> body, String key) {
        Object value = body.get(key);
        if (value == null || value.toString().isBlank()) {
            throw new IllegalArgumentException(key + " is required");
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
        getServletContext().log("Database failure during " + operation + ": " + ex.getMessage(), ex);
        json(response, HttpServletResponse.SC_INTERNAL_SERVER_ERROR,
                Map.of("error", "database operation failed", "detail", ex.getMessage()));
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
