from locust import HttpUser, task

class ReqResUser(HttpUser):
    @task
    def hello_world(self):
        self.client.get("/")
