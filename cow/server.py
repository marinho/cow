#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
from os.path import exists, join, isabs, abspath, split, expanduser, dirname
import logging
import inspect
import imp
import argparse

import tornado.ioloop
from tornado.web import Application
from tornado.httpserver import HTTPServer
from derpconf.config import Config

from cow.handlers.healthcheck import HealthCheckHandler


LOGS = {
    0: 'error',
    1: 'warning',
    2: 'info',
    3: 'debug'
}


class Server(object):
    def __init__(self, config=None):
        self.debug = False
        self.root_path = abspath(dirname(inspect.getfile(self.__class__)))
        self.default_config_path = join(self.root_path, 'config', 'local.conf')
        self.config = config

    def get_server_name(self):
        return "Server"

    @property
    def template_path(self):
        return join(self.root_path, 'templates')

    @property
    def static_path(self):
        return join(self.root_path, 'static')

    def get_config(self):
        return self.config_module()

    def get_plugins(self):
        return []

    def load_config_module(self):
        config_path = abspath(join(self.root_path.rstrip('/'), 'config'))
        module_path = join(config_path, '__init__.py')
        if exists(config_path) and exists(module_path):
            config = imp.load_source('cow.config', module_path)
            return config.Config

        return Config

    def get_app(self):
        handlers = [
            ('/healthcheck/?', HealthCheckHandler),
        ]

        handlers = list(self.get_handlers()) + handlers
        settings = self.get_settings()

        return Application(handlers, **settings)

    def get_handlers(self):
        return []

    def get_settings(self):
        return {
            'debug': self.debug,
            'template_path': self.template_path,
            'static_path': self.static_path,
        }

    def config_parser(self, parser):
        pass

    def plugin_after_start(self, *args, **kw):
        for plugin in self.application.plugins:
            plugin.after_start(self.application, *args, **kw)

    def plugin_before_end(self, *args, **kw):
        for plugin in self.application.plugins:
            plugin.before_end(self.application, *args, **kw)

    def initialize_app(self, conf=None):
        if conf is None:
            conf = self.default_config_path

        self.config_module = self.load_config_module()

        self.application = self.get_app()
        self.application.plugins = self.get_plugins()

        self.application.config = self.config
        if self.application.config is None:
            self.application.config = self.config_module.load(path=conf, conf_name=split(conf)[-1], lookup_paths=[
                os.curdir,
                expanduser('~'),
                '/etc/',
            ])

            logging.info("Using configuration file at {0}.".format(self.application.config.config_file))

    def start(self, args=None):
        if args is None:
            args = sys.argv[1:]

        parser = argparse.ArgumentParser()
        parser.add_argument('--port', '-p', type=int, default="2368", help="Port to start the server with.")
        parser.add_argument('--bind', '-b', default="0.0.0.0", help="IP to bind the server to.")
        parser.add_argument('--conf', '-c', default=self.default_config_path, help="Path to configuration file.")
        parser.add_argument('--verbose', '-v', action='count', default=0, help='Log level: v=warning, vv=info, vvv=debug.')
        parser.add_argument('--debug', '-d', action='store_true', default=False, help='Indicates whether to run in debug mode.')
        parser.add_argument('--workers', '-w', type=int, default="1", help="Number of forks to run tornado with. Defaults to 1.")

        self.config_parser(parser)
        options = parser.parse_args(args)

        self.debug = options.debug

        log_level = LOGS[options.verbose].upper()
        logging.basicConfig(level=getattr(logging, log_level), format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        print("Setting log-level to %s." % log_level)

        if not isabs(options.conf):
            logging.debug("Configuration file {0} is not absolute. Converting to abspath".format(options.conf))
            options.conf = abspath(options.conf)

        logging.info("Loading configuration file at {0}...".format(options.conf))

        self.initialize_app(options.conf)

        server = HTTPServer(self.application, xheaders=True)
        server_name = self.get_server_name()

        io_loop = None

        try:
            server.bind(options.port, options.bind)

            server.start(int(options.workers))

            io_loop = tornado.ioloop.IOLoop.instance()
            self.application.io_loop = io_loop

            self.plugin_after_start(io_loop=io_loop)

            logging.info('-- %s started listening in %s:%d --' % (server_name, options.bind, options.port))
            io_loop.start()
        except KeyboardInterrupt:
            if io_loop is not None:
                self.plugin_before_end(io_loop=io_loop)

            logging.info('')
            logging.info('-- %s closed by user interruption --' % server_name)

    @classmethod
    def run(cls):
        server = cls()
        server.start()
