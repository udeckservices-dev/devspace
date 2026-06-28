-- DevSpace - Database Schema
-- Run this script in your MySQL database

CREATE DATABASE IF NOT EXISTS devspace CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE devspace;

-- Users Table
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    role ENUM('admin', 'user') DEFAULT 'user',
    plan ENUM('free', 'basic', 'pro') DEFAULT 'free',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_email (email),
    INDEX idx_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Projects Table
CREATE TABLE IF NOT EXISTS projects (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(255) NOT NULL,
    repo_url VARCHAR(500) NOT NULL,
    branch VARCHAR(100) DEFAULT 'main',
    language ENUM('python', 'php', 'node') DEFAULT 'python',
    deploy_path VARCHAR(500) NOT NULL,
    last_deployed DATETIME NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_language (language)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Deployments Table
CREATE TABLE IF NOT EXISTS deployments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_id INT NOT NULL,
    status ENUM('pending', 'running', 'success', 'failed') DEFAULT 'pending',
    logs TEXT,
    commit_message VARCHAR(500) NULL,
    commit_date DATETIME NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    INDEX idx_project_id (project_id),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ⚠️ GENERATE YOUR OWN HASH BEFORE USING THIS SQL ⚠️
-- python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your-admin-password'))"
INSERT INTO users (name, email, password, role, plan) VALUES 
('Admin', 'admin@example.com', 'pbkdf2:sha256:600000$CHANGE_ME$0000000000000000000000000000000000000000000000000000000000000000', 'admin', 'pro');

-- Sample user for testing
INSERT INTO users (name, email, password, role, plan) VALUES 
('Test User', 'user@example.com', 'pbkdf2:sha256:600000$CHANGE_ME$0000000000000000000000000000000000000000000000000000000000000000', 'user', 'free');

-- Plan limits configuration
-- free: 1 project
-- basic: 5 projects
-- pro: unlimited (999)