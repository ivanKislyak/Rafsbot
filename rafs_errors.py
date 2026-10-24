class MissingBotTokenError(Exception):
    """An exception thrown when the Telegram bot token is missing"""
    def __init__(self, message="The BOT_TOKEN environment variable is not set. Please, check the .env file or create it near to run.py"):
        self.message = message
        super().__init__(self.message)