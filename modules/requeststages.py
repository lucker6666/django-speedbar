from __future__ import absolute_import

from django.core import urlresolvers
from django.core.handlers.base import BaseHandler

from .stacktracer import StackTracer

from functools import wraps
import traceback


def monkeypatch_method(cls):
    def decorator(func):
        original = getattr(cls, func.__name__)
        # We can't use partial as it doesn't return a real function
        def replacement(self, *args, **kwargs):
            func(original, self, *args, **kwargs)
        setattr(cls, func.__name__, replacement)
        return func
    return decorator


def trace(function, action_type, label):
    @wraps(function)
    def wrapper(*args, **kwargs):
        stack_tracer = StackTracer.instance()
        stack_tracer.push_stack(action_type, label)
        try:
            return function(*args, **kwargs)
        finally:
            stack_tracer.pop_stack()
    return wrapper

def patch_function_list(functions, action_type, format_string):
    for i, func in enumerate(functions):
        functions[i] = trace(func, action_type, format_string % (func.im_class.__name__),)

def wrap_middleware_with_tracers(request_handler):
    patch_function_list(request_handler._request_middleware, 'MIDDLEWARE_REQUEST', 'Middleware: %s (request)')
    patch_function_list(request_handler._view_middleware, 'MIDDLEWARE_VIEW', 'Middleware: %s (view)')
    patch_function_list(request_handler._template_response_middleware, 'MIDDLEWARE_TEMPLATE_RESPONSE', 'Middleware: %s (template response)')
    patch_function_list(request_handler._response_middleware, 'MIDDLEWARE_RESPONSE', 'Middleware: %s (response)')
    patch_function_list(request_handler._exception_middleware, 'MIDDLEWARE_EXCEPTION', 'Middleware: %s (exeption)')


def copymodule(old):
    new = type(old)(old.__name__, old.__doc__)
    new.__dict__.update(old.__dict__)
    return new



def monkey_patch():
    @monkeypatch_method(BaseHandler)
    def load_middleware(original, self, *args, **kwargs):
        original(self, *args, **kwargs)
        wrap_middleware_with_tracers(self)

    real_resolver_cls = urlresolvers.RegexURLResolver
    class ProxyRegexURLResolverMetaClass(urlresolvers.RegexURLResolver.__class__):
        def __instancecheck__(self, instance):
            return isinstance(instance, real_resolver_cls) or super(ProxyRegexURLResolverMetaClass, self).__instancecheck__(instance)
    class ProxyRegexURLResolver(object):
        __metaclass__ = ProxyRegexURLResolverMetaClass
        def __new__(cls, *args, **kwargs):
            real_object = real_resolver_cls(*args, **kwargs)
            stack = traceback.extract_stack()
            if stack[-2][2] == 'get_response':
                obj = super(ProxyRegexURLResolver, cls).__new__(cls)
                obj.other = real_object
                return obj
            else:
                return real_object
        def __getattr__(self, attr):
            return getattr(self.other, attr)
        def resolve(self, path):
            stack_tracer = StackTracer.instance()
            stack_tracer.push_stack('RESOLV', 'Resolving: ' + path)
            try:
                callbacks = self.other.resolve(path)
            finally:
                stack_tracer.pop_stack()
            callbacks.func = trace(callbacks.func, 'VIEW', 'View: ' + callbacks.view_name)
            return callbacks
    urlresolvers.RegexURLResolver = ProxyRegexURLResolver