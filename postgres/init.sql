CREATE TABLE IF NOT EXISTS members (
    id          BIGSERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    department  VARCHAR(100) NOT NULL,
    email       VARCHAR(200) NOT NULL UNIQUE
);

INSERT INTO members (name, department, email) VALUES
    ('田中 太郎', '営業部', 'tanaka@example.local'),
    ('佐藤 花子', '開発部', 'sato@example.local'),
    ('鈴木 一郎', '人事部', 'suzuki@example.local')
ON CONFLICT (email) DO NOTHING;
