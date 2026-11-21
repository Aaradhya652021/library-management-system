-- ============================================================================
-- 001_ml_feedback.sql
-- Idempotent schema for ML recommendations, feedback and segments.
-- Run with:  python scripts/migrate.py
--
-- Every statement is safe to run repeatedly.  ALTER TABLE changes are guarded
-- with information_schema lookups + PREPARE so no column/index/FK is added
-- twice.  Nothing is dropped or truncated.
-- ============================================================================

-- ---------------------------------------------------------------- feedback --
CREATE TABLE IF NOT EXISTS book_feedback (
  feedback_id INT NOT NULL AUTO_INCREMENT,
  user_id INT NOT NULL,
  book_id INT NOT NULL,
  issue_id INT NULL,
  rating TINYINT NOT NULL,
  comment VARCHAR(500) NULL,
  created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (feedback_id),
  UNIQUE KEY uq_book_feedback_user_book (user_id, book_id),
  KEY idx_book_feedback_book (book_id),
  KEY idx_book_feedback_issue (issue_id),
  CONSTRAINT fk_book_feedback_user FOREIGN KEY (user_id)
    REFERENCES users (user_id) ON DELETE CASCADE,
  CONSTRAINT fk_book_feedback_book FOREIGN KEY (book_id)
    REFERENCES books (book_id) ON DELETE CASCADE,
  CONSTRAINT fk_book_feedback_issue FOREIGN KEY (issue_id)
    REFERENCES issues (issue_id) ON DELETE SET NULL,
  CONSTRAINT chk_book_feedback_rating CHECK (rating BETWEEN 1 AND 5)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------- segments --
-- The live database may already have a legacy `segments` table containing a
-- `label` column.  Create it with the new shape on a fresh database; on an
-- existing database the CREATE is a no-op and the guards below add columns.
CREATE TABLE IF NOT EXISTS segments (
  segment_id INT NOT NULL AUTO_INCREMENT,
  label VARCHAR(140) NULL,
  name VARCHAR(140) NULL,
  description VARCHAR(500) NULL,
  kind ENUM('ml', 'feedback') NOT NULL DEFAULT 'ml',
  source_book_id INT NULL,
  sentiment ENUM('positive', 'neutral', 'negative') NULL,
  ml_cluster TINYINT NULL,
  top_genres VARCHAR(255) NULL,
  created_by INT NULL,
  created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (segment_id),
  KEY idx_segments_kind_cluster (kind, ml_cluster),
  CONSTRAINT fk_segments_source_book FOREIGN KEY (source_book_id)
    REFERENCES books (book_id) ON DELETE SET NULL,
  CONSTRAINT fk_segments_creator FOREIGN KEY (created_by)
    REFERENCES admin (admin_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Make the legacy label column optional for new rows.
SET @ddl = (SELECT IF(IS_NULLABLE = 'NO',
  'ALTER TABLE segments MODIFY COLUMN label VARCHAR(140) NULL',
  'DO 0')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'segments' AND COLUMN_NAME = 'label');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE segments ADD COLUMN name VARCHAR(140) NULL AFTER label',
  'DO 0')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'segments' AND COLUMN_NAME = 'name');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

-- Legacy rows used `label` as the display name.
UPDATE segments SET name = label WHERE name IS NULL AND label IS NOT NULL;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE segments ADD COLUMN description VARCHAR(500) NULL',
  'DO 0')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'segments' AND COLUMN_NAME = 'description');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE segments ADD COLUMN kind ENUM(''ml'', ''feedback'') NOT NULL DEFAULT ''ml''',
  'DO 0')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'segments' AND COLUMN_NAME = 'kind');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE segments ADD COLUMN source_book_id INT NULL',
  'DO 0')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'segments' AND COLUMN_NAME = 'source_book_id');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE segments ADD COLUMN sentiment ENUM(''positive'', ''neutral'', ''negative'') NULL',
  'DO 0')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'segments' AND COLUMN_NAME = 'sentiment');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE segments ADD COLUMN ml_cluster TINYINT NULL',
  'DO 0')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'segments' AND COLUMN_NAME = 'ml_cluster');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE segments ADD COLUMN top_genres VARCHAR(255) NULL',
  'DO 0')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'segments' AND COLUMN_NAME = 'top_genres');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE segments ADD COLUMN created_by INT NULL',
  'DO 0')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'segments' AND COLUMN_NAME = 'created_by');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE segments ADD COLUMN created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP',
  'DO 0')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'segments' AND COLUMN_NAME = 'created_at');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE segments ADD CONSTRAINT fk_segments_source_book FOREIGN KEY (source_book_id) REFERENCES books (book_id) ON DELETE SET NULL',
  'DO 0')
  FROM information_schema.TABLE_CONSTRAINTS
  WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'segments'
    AND CONSTRAINT_NAME = 'fk_segments_source_book');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE segments ADD CONSTRAINT fk_segments_creator FOREIGN KEY (created_by) REFERENCES admin (admin_id) ON DELETE SET NULL',
  'DO 0')
  FROM information_schema.TABLE_CONSTRAINTS
  WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'segments'
    AND CONSTRAINT_NAME = 'fk_segments_creator');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

-- --------------------------------------------------------- segment members --
CREATE TABLE IF NOT EXISTS segment_members (
  segment_id INT NOT NULL,
  user_id INT NOT NULL,
  assigned_by ENUM('auto', 'admin') NOT NULL DEFAULT 'auto',
  created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (segment_id, user_id),
  KEY idx_segment_members_user (user_id),
  CONSTRAINT fk_segment_members_segment FOREIGN KEY (segment_id)
    REFERENCES segments (segment_id) ON DELETE CASCADE,
  CONSTRAINT fk_segment_members_user FOREIGN KEY (user_id)
    REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------------- segment books --
CREATE TABLE IF NOT EXISTS segment_books (
  id INT NOT NULL AUTO_INCREMENT,
  segment_id INT NOT NULL,
  ml_idx INT NOT NULL,
  book_id INT NULL,
  note VARCHAR(255) NULL,
  created_by INT NULL,
  created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_segment_books_segment_ml (segment_id, ml_idx),
  KEY idx_segment_books_book (book_id),
  CONSTRAINT fk_segment_books_segment FOREIGN KEY (segment_id)
    REFERENCES segments (segment_id) ON DELETE CASCADE,
  CONSTRAINT fk_segment_books_book FOREIGN KEY (book_id)
    REFERENCES books (book_id) ON DELETE SET NULL,
  CONSTRAINT fk_segment_books_creator FOREIGN KEY (created_by)
    REFERENCES admin (admin_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ----------------------------------------------------- library -> ML index --
SET @ddl = (SELECT IF(COUNT(*) = 0,
  'ALTER TABLE books ADD COLUMN ml_idx INT NULL',
  'DO 0')
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'books' AND COLUMN_NAME = 'ml_idx');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @ddl = (SELECT IF(COUNT(*) = 0,
  'CREATE UNIQUE INDEX uq_books_ml_idx ON books (ml_idx)',
  'DO 0')
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'books'
    AND INDEX_NAME = 'uq_books_ml_idx');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;
