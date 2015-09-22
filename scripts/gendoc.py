#! /usr/bin/env python

from docutils.core import publish_file
import fileinput
import glob
import os
import re
import shutil
import subprocess
import sys
import yaml

os.chdir(os.path.dirname(os.path.abspath(__file__)))

stylesheets = {
    "stylesheet_path": ["basic.css", "nature.css", "codehighlight.css"]
}


"""
Read a RST file and replace titles with a different title level if required.
Args:
    filename: The name of the file being read (for debugging)
    file_stream: The open file stream to read from.
    title_level: The integer which determines the offset to *start* from.
    title_styles: An array of characters detailing the right title styles to use
                  e.g. ["=", "-", "~", "+"]
Returns:
    string: The file contents with titles adjusted.
Example:
    Assume title_styles = ["=", "-", "~", "+"], title_level = 1, and the file
    when read line-by-line encounters the titles "===", "---", "---", "===", "---".
    This function will bump every title encountered down a sub-heading e.g.
    "=" to "-" and "-" to "~" because title_level = 1, so the output would be
    "---", "~~~", "~~~", "---", "~~~". There is no bumping "up" a title level.
"""
def load_with_adjusted_titles(filename, file_stream, title_level, title_styles):
    rst_lines = []
    title_chars = "".join(title_styles)
    title_regex = re.compile("^[" + re.escape(title_chars) + "]{3,}$")

    prev_line_title_level = 0 # We expect the file to start with '=' titles
    file_offset = None
    prev_non_title_line = None
    for i, line in enumerate(file_stream, 1):
        # ignore anything which isn't a title (e.g. '===============')
        if not title_regex.match(line):
            rst_lines.append(line)
            prev_non_title_line = line
            continue
        # The title underline must match at a minimum the length of the title
        if len(prev_non_title_line) > len(line):
            rst_lines.append(line)
            prev_non_title_line = line
            continue

        line_title_style = line[0]
        line_title_level = title_styles.index(line_title_style)

        # Not all files will start with "===" and we should be flexible enough
        # to allow that. The first title we encounter sets the "file offset"
        # which is added to the title_level desired.
        if file_offset is None:
            file_offset = line_title_level
            if file_offset != 0:
                print ("     WARNING: %s starts with a title style of '%s' but '%s' " +
                    "is preferable.") % (filename, line_title_style, title_styles[0])

        # Sanity checks: Make sure that this file is obeying the title levels
        # specified and bail if it isn't.
        # The file is allowed to go 1 deeper or any number shallower
        if prev_line_title_level - line_title_level < -1:
            raise Exception(
                ("File '%s' line '%s' has a title " +
                "style '%s' which doesn't match one of the " +
                "allowed title styles of %s because the " +
                "title level before this line was '%s'") %
                (filename, (i + 1), line_title_style, title_styles,
                title_styles[prev_line_title_level])
            )
        prev_line_title_level = line_title_level

        adjusted_level = (
            title_level + line_title_level - file_offset
        )

        # Sanity check: Make sure we can bump down the title and we aren't at the
        # lowest level already
        if adjusted_level >= len(title_styles):
            raise Exception(
                ("Files '%s' line '%s' has a sub-title level too low and it " +
                "cannot be adjusted to fit. You can add another level to the " +
                "'title_styles' key in targets.yaml to fix this.") %
                (filename, (i + 1))
            )

        if adjusted_level == line_title_level:
            # no changes required
            rst_lines.append(line)
            continue

        # Adjusting line levels
        # print (
        #     "File: %s Adjusting %s to %s because file_offset=%s title_offset=%s" %
        #     (filename, line_title_style,
        #         title_styles[adjusted_level],
        #         file_offset, title_level)
        # )
        rst_lines.append(line.replace(
            line_title_style,
            title_styles[adjusted_level]
        ))
            
    return "".join(rst_lines)


def get_rst(file_info, title_level, title_styles, spec_dir, adjust_titles):
    # string are file paths to RST blobs
    if isinstance(file_info, basestring):
        print "%s %s" % (">" * (1 + title_level), file_info)
        with open(spec_dir + file_info, "r") as f:
            rst = None
            if adjust_titles:
                rst = load_with_adjusted_titles(
                    file_info, f, title_level, title_styles
                )
            else:
                rst = f.read()
            if rst[-2:] != "\n\n":
                raise Exception(
                    ("File %s should end with TWO new-line characters to ensure " +
                    "file concatenation works correctly.") % (file_info,)
                )
            return rst
    # dicts look like {0: filepath, 1: filepath} where the key is the title level
    elif isinstance(file_info, dict):
        levels = sorted(file_info.keys())
        rst = []
        for l in levels:
            rst.append(get_rst(file_info[l], l, title_styles, spec_dir, adjust_titles))
        return "".join(rst)
    # lists are multiple file paths e.g. [filepath, filepath]
    elif isinstance(file_info, list):
        rst = []
        for f in file_info:
            rst.append(get_rst(f, title_level, title_styles, spec_dir, adjust_titles))
        return "".join(rst)
    raise Exception(
        "The following 'file' entry in this target isn't a string, list or dict. " +
        "It really really should be. Entry: %s" % (file_info,)
    )


def build_spec(target, out_filename):
    with open(out_filename, "wb") as outfile:
        for file_info in target["files"]:
            section = get_rst(
                file_info=file_info,
                title_level=0,
                title_styles=target["title_styles"],
                spec_dir="../specification/",
                adjust_titles=True
            )
            outfile.write(section)


"""
Replaces relative title styles with actual title styles.

The templating system has no idea what the right title style is when it produces
RST because it depends on the build target. As a result, it uses relative title
styles defined in targets.yaml to say "down a level, up a level, same level".

This function replaces these relative titles with actual title styles from the
array in targets.yaml.
"""
def fix_relative_titles(target, filename, out_filename):
    title_styles = target["title_styles"] # ["=", "-", "~", "+"]
    relative_title_chars = [ # ["<", "/", ">"]
        target["relative_title_styles"]["subtitle"],
        target["relative_title_styles"]["sametitle"],
        target["relative_title_styles"]["supertitle"]
    ]
    relative_title_matcher = re.compile(
        "^[" + re.escape("".join(relative_title_chars)) + "]{3,}$"
    )
    title_matcher = re.compile(
        "^[" + re.escape("".join(title_styles)) + "]{3,}$"
    )
    current_title_style = None
    with open(filename, "r") as infile:
        with open(out_filename, "w") as outfile:
            for line in infile.readlines():
                if not relative_title_matcher.match(line):
                    if title_matcher.match(line):
                        current_title_style = line[0]
                    outfile.write(line)
                    continue
                line_char = line[0]
                replacement_char = None
                current_title_level = title_styles.index(current_title_style)
                if line_char == target["relative_title_styles"]["subtitle"]:
                    if (current_title_level + 1) == len(title_styles):
                        raise Exception(
                            "Encountered sub-title line style but we can't go " +
                            "any lower."
                        )
                    replacement_char = title_styles[current_title_level + 1]
                elif line_char == target["relative_title_styles"]["sametitle"]:
                    replacement_char = title_styles[current_title_level]
                elif line_char == target["relative_title_styles"]["supertitle"]:
                    if (current_title_level - 1) < 0:
                        raise Exception(
                            "Encountered super-title line style but we can't go " +
                            "any higher."
                        )
                    replacement_char = title_styles[current_title_level - 1]
                else:
                    raise Exception(
                        "Unknown relative line char %s" % (line_char,)
                    )

                outfile.write(
                    line.replace(line_char, replacement_char)
                )



def rst2html(i, o):
    with open(i, "r") as in_file:
        with open(o, "w") as out_file:
            publish_file(
                source=in_file,
                destination=out_file,
                reader_name="standalone",
                parser_name="restructuredtext",
                writer_name="html",
                settings_overrides=stylesheets
            )


def run_through_template(input):
    tmpfile = './tmp/output'
    try:
        with open(tmpfile, 'w') as out:
            print subprocess.check_output(
                [
                    'python', 'build.py', "-v",
                    "-i", "matrix_templates",
                    "-o", "../scripts/tmp",
                    "../scripts/"+input
                ],
                stderr=out,
                cwd="../templating",
            )
    except subprocess.CalledProcessError as e:
        with open(tmpfile, 'r') as f:
            sys.stderr.write(f.read() + "\n")
        raise


def get_build_target(targets_listing, target_name):
    build_target = {
        "title_styles": [],
        "relative_title_styles": {},
        "files": []
    }
    with open(targets_listing, "r") as targ_file:
        all_targets = yaml.load(targ_file.read())
        build_target["title_styles"] = all_targets["title_styles"]
        build_target["relative_title_styles"] = all_targets["relative_title_styles"]
        target = all_targets["targets"].get(target_name)
        if not target:
            raise Exception(
                "No target by the name '" + target_name + "' exists in '" +
                targets_listing + "'."
            )
        if not isinstance(target.get("files"), list):
            raise Exception(
                "Found target but 'files' key is not a list."
            )

        def get_group(group_id):
            group_name = group_id[len("group:"):]
            group = all_targets.get("groups", {}).get(group_name)
            if not group:
                raise Exception(
                    "Tried to find group '" + group_name + "' but it " +
                    "doesn't exist."
                )
            return group

        resolved_files = []
        for f in target["files"]:
            group = None
            if isinstance(f, basestring) and f.startswith("group:"):
                group = get_group(f)
            elif isinstance(f, dict):
                for (k, v) in f.iteritems():
                    if isinstance(v, basestring) and v.startswith("group:"):
                        f[k] = get_group(v)
                resolved_files.append(f)
                continue

            if group:
                if isinstance(group, list):
                    resolved_files.extend(group)
                else:
                    resolved_files.append(group)
            else:
                resolved_files.append(f)
        build_target["files"] = resolved_files
    return build_target


def prepare_env():
    try:
        os.makedirs("./gen")
    except OSError:
        pass
    try:
        os.makedirs("./tmp")
    except OSError:
        pass


def cleanup_env():
    shutil.rmtree("./tmp")


def main(target_name):
    prepare_env()
    print "Building spec [target=%s]" % target_name
    target = get_build_target("../specification/targets.yaml", target_name)
    build_spec(target=target, out_filename="tmp/templated_spec.rst")
    run_through_template("tmp/templated_spec.rst")
    fix_relative_titles(
        target=target, filename="tmp/templated_spec.rst",
        out_filename="tmp/full_spec.rst"
    )
    shutil.copy("../supporting-docs/howtos/client-server.rst", "tmp/howto.rst")
    run_through_template("tmp/howto.rst")
    rst2html("tmp/full_spec.rst", "gen/specification.html")
    rst2html("tmp/howto.rst", "gen/howtos.html")
    if "--nodelete" not in sys.argv:
        cleanup_env()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1:] != ["--nodelete"]:
        # we accept almost no args, so they don't know what they're doing!
        print "gendoc.py - Generate the Matrix specification as HTML."
        print "Usage:"
        print "  python gendoc.py [--nodelete]"
        print ""
        print "The specification can then be found in the gen/ folder."
        print ("If --nodelete was specified, intermediate files will be "
               "present in the tmp/ folder.")
        print ""
        print "Requirements:"
        print " - This script requires Jinja2 and rst2html (docutils)."
        sys.exit(0)
    main("main")
