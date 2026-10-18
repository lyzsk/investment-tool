CREATE TABLE cls_telegraph (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    cls_id BIGINT NOT NULL,
    title VARCHAR(255),
    brief TEXT,
    content TEXT,
    level VARCHAR(10),
    publish_time DATETIME,
    author VARCHAR(100),
    images TEXT,
    is_deleted TINYINT DEFAULT 0,
    create_time DATETIME,
    update_time DATETIME,
    status INT
);