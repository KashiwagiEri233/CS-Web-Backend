pipeline {
    agent { label 'slave1' } 

    environment {
        WORK_DIR = "/mnt"
        GIT_URL = "http://root:REDACTED_GITLAB_TOKEN@192.168.100.16:30080/Thewitchcat/rongqi-stock-backend.git"
    }

    triggers {
        GenericTrigger(
            token: 'rongqi-stock-backend-webhook-token',
            genericVariables: [
                [key: 'ref', value: '$.ref']
            ],
            causeString: 'Triggered on branch $ref',
            printPostContent: false,
            printContributedVariables: true,
            regexpFilterText: '$ref',
            regexpFilterExpression: '.*'
        )
    }

    stages {
        stage('Checkout') {
            steps {
                dir("${WORK_DIR}") {
                    sh """
                        # 如果目录存在先删除，避免重复 clone 报错
                        rm -rf rongqi-stock-backend
                        git clone ${GIT_URL}
                    """
                }
            }
        }

        stage('Build & Deploy') {
            steps {
                dir("${WORK_DIR}/rongqi-stock-backend") {
                    sh """
                        docker-compose down 
                        docker-compose build
                        docker-compose up -d
                    """
                }
            }
        }
    }

    post {
        success {
            echo "✅ Pipeline executed successfully!"
        }
        failure {
            echo "❌ Pipeline failed. Check logs."
        }
    }
}
