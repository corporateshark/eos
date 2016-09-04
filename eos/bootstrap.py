import os
import shutil
import eos.archive
import eos.cache
import eos.constants
import eos.fallback
import eos.log
import eos.post
import eos.repo
import eos.util


def bootstrap_library(json_obj, name, library_dir, postprocessing_dir, create_snapshots=False,
                      fallback_server_url=None):
    eos.log("Bootstrapping library '" + name + "' to " + library_dir)

    # create directory for library
    if not os.path.exists(library_dir):
        os.mkdir(library_dir)

    # get library

    src = json_obj.get('source', None)
    if not src:
        eos.log_warning("library '" + name + "' is missing source description")
        return False

    src_type = src.get('type', None)
    src_url = src.get('url', None)

    if not src_type or not src_url:
        eos.log_warning("library '" + name + "' is missing type or URL description")
        return False

    if src_type not in ['archive', 'git', 'hg', 'svn']:
        eos.log_warning("unknown source type for library '" + name)
        return False

    def get_from_fallback(filename, download_dir):
        if fallback_server_url is None:
            return False
        eos.log("downloading repository from fallback URL %s..." % fallback_server_url)
        fallback_success = eos.fallback.download_and_extract_from_fallback_url(fallback_server_url, filename,
                                                                               download_dir, library_dir)
        if not fallback_success:
            eos.log_error("download from fallback URL failed")
        return fallback_success

    if src_type == "archive":
        # We're dealing with an archive file
        sha1_hash = src.get('sha1', None)
        user_agent = src.get('user-agent', None)

        # download archive file
        download_filename = eos.util.download_file(src_url, eos.cache.get_archive_dir(), sha1_hash, user_agent)
        if download_filename == "":
            eos.log_error("downloading of file for '" + name + "' from " + src_url + " failed")
            return get_from_fallback(os.path.basename(download_filename), eos.cache.get_archive_dir())

        if os.path.exists(library_dir):
            shutil.rmtree(library_dir)

        # extract archive file
        if not eos.archive.extract_file(download_filename, library_dir):
            eos.log_error("extraction of file for '" + download_filename + "' failed")
            return get_from_fallback(os.path.basename(download_filename), eos.cache.get_archive_dir())
    else:
        # We're dealing with a repository
        branch = src.get('branch', None)
        if not branch:
            branch = src.get('branch-follow', None)
        revision = src.get('revision', None)

        if branch and revision:
            eos.log_error("cannot specify both branch (to follow) and revision for repository '" + name + "'")
            return False

        snapshot_archive_name = name + ".tar.gz"  # filename for reading/writing snapshots
        if revision is not None:
            snapshot_archive_name = name + "_" + revision + ".tar.gz"  # add the revision number, if present

        # clone or update repository
        if not eos.repo.update_state(src_type, src_url, name, library_dir, branch, revision):
            eos.log_error("updating repository state for '" + name + " failed")
            fallback_success = get_from_fallback(snapshot_archive_name, eos.cache.get_snapshot_dir())
            if not fallback_success:
                return False
            fallback_success = eos.repo.update_state(src_type, None, name, library_dir, branch, revision)
            if not fallback_success:
                eos.log_error("updating state from downloaded repository from fallback URL failed")
                return False

        # optionally create snapshot
        if create_snapshots:
            eos.log("Creating snapshot of '" + name + "' repository...")
            snapshot_archive_filename = os.path.join(eos.cache.get_snapshot_dir(), snapshot_archive_name)
            eos.log_verbose("Snapshot will be written to " + snapshot_archive_filename)
            eos.archive.create_archive_from_directory(library_dir, snapshot_archive_filename, revision is None)

    # post-process library

    post = json_obj.get('postprocess', None)
    if not post:
        return True  # it's optional

    post_type = post.get('type', None)
    if not post_type:
        eos.log_error("postprocessing object for library '" + name + "' must have a 'type'")
        return False

    post_file = post.get('file', None)
    if not post_file:
        eos.log_error("postprocessing object for library '" + name + "' must have a 'file'")
        return False

    if post_type not in ['patch', 'script']:
        eos.log_error("unknown postprocessing type for library '" + name + "'")
        return False

    if post_type == "patch":
        pnum = post.get('pnum', 2)
        # If we have a postprocessing directory specified, make it an absolute path
        if postprocessing_dir:
            post_file = os.path.join(postprocessing_dir, post_file)
        # Try to apply patch
        if not eos.post.apply_patch(name, library_dir, post_file, pnum):
            eos.log_error("patch application of " + post_file + " failed for library '" + name + "'")
            return False
    elif post_type == "script":
        # Try to run script
        if not eos.post.run_script(post_file):
            eos.log_error("script execution of " + post_file + " failed for library '" + name + "'")
            return False

    return True

