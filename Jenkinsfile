def runCommand(String command) {
    if (isUnix()) {
        sh command
    } else {
        bat command
    }
}

def runPythonModule(String arguments) {
    runCommand(isUnix() ? "python3 -m ${arguments}" : "python -m ${arguments}")
}

pipeline {
    agent any

    options {
        // 同一 agent 上并发构建会因固定端口（54329/63799）与默认 compose 项目名
        // 互相踩踏（post 阶段的 down -v 会拆掉另一个构建的服务），必须互斥。
        disableConcurrentBuilds()
        // 迁移 / docker 卡住时防止构建无限挂起
        timeout(time: 30, unit: 'MINUTES')
        timestamps()
    }

    environment {
        ENV_FILE = '.env.test'
        TEST_DATABASE_URL = 'postgresql+asyncpg://postgres:postgres@127.0.0.1:54329/witchcat_test'
        DATABASE_URL = 'postgresql+asyncpg://postgres:postgres@127.0.0.1:54329/witchcat_test'
        TEST_REDIS_URL = 'redis://127.0.0.1:63799/0'
        REDIS_URL = 'redis://127.0.0.1:63799/0'
        REQUIRE_INTEGRATION_DB = '1'
        REQUIRE_INTEGRATION_REDIS = '1'
        TESTING = 'True'
        DB_AUTO_CREATE_DATABASE = 'False'
    }

    stages {
        stage('Install') {
            steps {
                script {
                    runCommand(isUnix()
                        ? 'python3 -c "import sys; assert sys.version_info >= (3, 13), sys.version"'
                        : 'python -c "import sys; assert sys.version_info >= (3, 13), sys.version"')
                    runPythonModule('pip install --require-hashes -r requirements-dev.lock')
                }
            }
        }
        stage('Start test services') {
            steps {
                script {
                    runCommand('docker compose -f docker-compose.ci.yml up -d --wait')
                }
            }
        }
        stage('Migration round trip') {
            steps {
                script {
                    runPythonModule('alembic upgrade head')
                    runPythonModule('alembic downgrade base')
                    runPythonModule('alembic upgrade head')
                }
            }
        }
        stage('Static checks') {
            steps {
                script {
                    runPythonModule('compileall -q app alembic scripts tests')
                    runPythonModule('black --check app tests alembic scripts run.py')
                    runPythonModule('flake8 app tests alembic scripts run.py')
                    runPythonModule('mypy')
                }
            }
        }
        stage('Tests') {
            steps {
                script {
                    // 覆盖率阈值单一事实源在 .coveragerc（fail_under），此处不重复指定
                    runPythonModule('pytest')
                }
            }
        }
        stage('Supply chain') {
            steps {
                script {
                    runCommand(isUnix() ? 'mkdir -p build' : 'if not exist build mkdir build')
                    // 运行时与开发依赖都审：CI 环境自身的工具链漏洞也在视野内
                    runPythonModule('pip_audit -r requirements.lock --no-deps --disable-pip --progress-spinner off')
                    runPythonModule('pip_audit -r requirements-dev.lock --no-deps --disable-pip --progress-spinner off')
                    runPythonModule('cyclonedx_py requirements requirements.lock --of JSON -o build/sbom.json')
                    runPythonModule('piplicenses --format=json --output-file=build/licenses.json --fail-on="GPL-3.0-only;GPL-3.0-or-later;AGPL-3.0-only;AGPL-3.0-or-later"')
                }
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: 'build/*.json,build/coverage.xml', allowEmptyArchive: true
            script {
                runCommand('docker compose -f docker-compose.ci.yml down -v --remove-orphans')
            }
        }
    }
}
