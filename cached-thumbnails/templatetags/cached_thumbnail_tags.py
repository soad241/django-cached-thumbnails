from django.template import Library, Node, VariableDoesNotExist, \
    TemplateSyntaxError
from easy_thumbnails import utils
from easy_thumbnails.files import get_thumbnailer
from django.db.models.fields.files import ImageFieldFile, FieldFile
from django.utils.html import escape
import re

register = Library()

RE_SIZE = re.compile(r'(\d+)x(\d+)$')

VALID_OPTIONS = utils.valid_processor_options()
VALID_OPTIONS.remove('size')
TIMEOUT_CACHE = 120

from easy_thumbnails.templatetags.thumbnail import ThumbnailNode, split_args
from django.core.cache import cache

class CachedThumbnailNode(ThumbnailNode):
    def render(self, context):
        # Note that this isn't a global constant because we need to change the
        # value for tests.
        raise_errors = utils.get_setting('DEBUG')
        # Get the source file.
        try:
            source = self.source_var.resolve(context)
        except VariableDoesNotExist:
            if raise_errors:
                raise VariableDoesNotExist("Variable '%s' does not exist." %
                        self.source_var)
            return self.bail_out(context)
        if not source:
            if raise_errors:
                raise TemplateSyntaxError(
                    "Variable '%s' is an invalid source." % self.source_var
                )
            return self.bail_out(context)
        # Resolve the thumbnail option values.
        try:
            opts = {}
            for key, value in self.opts.iteritems():
                if hasattr(value, 'resolve'):
                    value = value.resolve(context)
                opts[str(key)] = value
        except Exception:
            if raise_errors:
                raise
            return self.bail_out(context)
        # Size variable can be either a tuple/list of two integers or a
        # valid string.
        size = opts['size']
        if isinstance(size, basestring):
            m = RE_SIZE.match(size)
            if m:
                opts['size'] = (int(m.group(1)), int(m.group(2)))
            else:
                if raise_errors:
                    raise TemplateSyntaxError("%r is not a valid size." % size)
                return self.bail_out(context)
        # Ensure the quality is an integer.
        if 'quality' in opts:
            try:
                opts['quality'] = int(opts['quality'])
            except (TypeError, ValueError):
                if raise_errors:
                    raise TemplateSyntaxError("%r is an invalid quality." %
                                              opts['quality'])
                return self.bail_out(context)

        # first try to get the thumbnail url from cache, if it is available
        # just return it otherwise create the thumb
        if isinstance(source, basestring):
            relname = source
        elif isinstance(source, FieldFile):
            relname = source.name
        else:
            relname = str(source)

        opt_str = ""
        for key in opts.keys():
            opt_str += "{0}_{1}".format(key, opts[key])

        cache_key = "{0}{1}".format(relname, opt_str)
        cache_key = escape(cache_key).replace(" ", "_").replace("(", "").\
                    replace(")", "").replace(",","")
        cache_key = str(hash(cache_key))
        thumb_url = False
        if thumb_url:
            if not self.context_name:
                return thumb_url
        # if the thumb is not cached create one and cache it
        try:
            thumbnail = get_thumbnailer(source).get_thumbnail(opts)
        except Exception:
            if raise_errors:
                raise
            result = self.bail_out(context)
            #cache.set(cache_key, result, TIMEOUT_CACHE)
            return result
        # Return the thumbnail file url, or put the file on the context.
        if self.context_name is None:
            result = escape(thumbnail.url)
            cache.set(cache_key, result, TIMEOUT_CACHE)
            return result
        else:
            context[self.context_name] = thumbnail
            return ''



def cached_thumbnail(parser, token):
    args = token.split_contents()
    tag = args[0]

    # Check to see if we're setting to a context variable.
    if len(args) > 4 and args[-2] == 'as':
        context_name = args[-1]
        args = args[:-2]
    else:
        context_name = None

    if len(args) < 3:
        raise TemplateSyntaxError("Invalid syntax. Expected "
            "'{%% %s source size [option1 option2 ...] %%}' or "
            "'{%% %s source size [option1 option2 ...] as variable %%}'" %
            (tag, tag))

    opts = {}

    # The first argument is the source file.
    source_var = parser.compile_filter(args[1])

    # The second argument is the requested size. If it's the static "10x10"
    # format, wrap it in quotes so that it is compiled correctly.
    size = args[2]
    match = RE_SIZE.match(size)
    if match:
        size = '"%s"' % size
    opts['size'] = parser.compile_filter(size)

    # All further arguments are options.
    args_list = split_args(args[3:]).items()
    for arg, value in args_list:
        if arg in VALID_OPTIONS:
            if value and value is not True:
                value = parser.compile_filter(value)
            opts[arg] = value
        else:
            raise TemplateSyntaxError("'%s' tag received a bad argument: "
                                      "'%s'" % (tag, arg))
    return CachedThumbnailNode(source_var, opts=opts, context_name=context_name)

register.tag(cached_thumbnail)
