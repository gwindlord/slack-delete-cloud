from google.cloud import secretmanager
from json import loads
from os import environ
from requests import get
from time import time, strftime, localtime

# bytes to MB
MBFACTOR = float(1<<20)

# mimetypes of files to delete (Slack API 'types' sometimes omits items with no reason)
mimetypes = (
#                'audio',
#                'image',
#                'video'
                'document'
            )


def check_arg(arg_name, request, default_value):
    """
    Check argument in incoming request, return given value if exists, or default one.
    Args:
        arg_name (str): argument name to look for
        request (flask.Request): HTTP request to look in
        default_value (str): value for argument if not found in request.
    Returns:
        Argument value (str), either found, or default.
    """
    request_json = request.get_json()
    if request.args and arg_name in request.args:
        result = request.args.get(arg_name)
    elif request_json and arg_name in request_json:
        result = request_json[arg_name]
    else:
        result = default_value
    return result


def main(request):
    """Responds to any HTTP request.
    Args:
        request (flask.Request): HTTP request object.
    Returns:
        The response text or any set of values that can be turned into a
        Response object using
        `make_response <http://flask.pocoo.org/docs/1.0/api/#flask.Flask.make_response>`.
    """
    days_count = check_arg('days', request, 30)
    files_count = check_arg('count', request, 1000)
    dry_run = check_arg('just_a_test', request, 1)

    title_result = f'[i] {current_timestamp()} Deleting files older than {days_count} days'

    project_id = environ.get('GCP_PROJECT')
    secret_id = environ.get('SLACK_TOKEN_SECRET')
    print(f"[*] Getting Slack token from project {project_id} secret {secret_id}..")
    client = secretmanager.SecretManagerServiceClient()
    resource_name = f'projects/{project_id}/secrets/{secret_id}/versions/latest'
    response = client.access_secret_version(request={'name': resource_name})
    slack_token = response.payload.data.decode('UTF-8')

    print("[*] Fetching file list..")
    files = list_files(token=slack_token, days=days_count, count=files_count)

    size_to_delete = sum([int(f['size']) for f in files])
    num_files = len(files)
    files_found = f"[i] {current_timestamp()} Found {num_files} files in {format(size_to_delete/MBFACTOR, '.2f')} MB"

    print("[*] Deleting files..")
    report = delete_files(
        token=slack_token, files=files, view_only=dry_run,
        fsize=size_to_delete, amount=num_files)

    print("[*] Done")

    # loaded webpage content
    return f'{title_result}<br><br>{files_found}<br><br>{report}'


def calculate_days(days):
    """
    Calculate days to unix time.
    Args:
        days (str): days amount to convert
    Returns:
        Same days amount in seconds (int)
    """
    return int(time()) - int(days) * 24 * 60 * 60


def current_timestamp():
    """
    Return current timestamp in %Y-%m-%d %H:%M:%S form (str).
    """
    return strftime('%Y-%m-%d %H:%M:%S')


def list_files(token, days, count):
    """
    Get a list of all files.
    Args:
        token (str): Slack API token
        days (str): files to list age in days
        count (str, int): files count to list
    Returns:
        List[Dict[str, str]] of files with their info
    """
    params = {'token': token, 'count': int(count), 'ts_to': calculate_days(days)}
    uri ='https://slack.com/api/files.list'
    response = get(uri, params=params)
    resp = loads(response.text)['files']
    files = []

    for f in resp:
        if any([mimetype in f['mimetype'] for mimetype in mimetypes]):
            files.append({
                'id': f['id'],
                'name': f['name'],
                'timestamp': strftime('%Y-%m-%d %H:%M:%S', localtime(f['timestamp'])),
                'mimetype': f['mimetype'],
                'size': f['size']
            })

    return files


def delete_files(token, files, view_only, fsize, amount):
    """
    Delete a list of files by id.
    Args:
        token (str): Slack API token
        files (List[Dict[str, str]]): files with their info
        view_only (bool): dry run flag
        fsize (int): files size to delete (only for logging)
        amount (int): number of files to delete (only for logging)
    Returns:
        Deletion statistics (str) for webpage contents
    """
    try:
        count = 0
        deleted_size = 0
        return_value = ''
        uri ='https://slack.com/api/files.delete'
        dry_run_message = '[i] DRY RUN, NO FILES DELETED\n'

        print(f"[*] Found {amount} files in {fsize} bytes")
        print(
            [(f['id'], f['name'], f['timestamp'], f['mimetype'], f['size']) for f in files])

        if int(view_only) == 1:
            return_value += dry_run_message
            return

        for f in files:
            count += 1
            deleted_size += f['size']
            params = {'token': token, 'file': f['id']}
            dresponse = loads(get(uri, params=params).text)
            if dresponse['ok']:
                print(f"[+] Deleted: [{f['id']}] {f['name']} ({f['timestamp']})")
            else:
                print(f"[!] Unable to delete: [{f['id']}] {f['name']}, reason: {dresponse['error']}")

    except Exception as e:
        return_value += '<br><br>' + str(e) + '<br><br>'
        print(f"[#] {str(e)}")

    finally:
        return_value += (
                          f"[i] {current_timestamp()} Attempted to delete {format(fsize/MBFACTOR, '.2f')} MB in {amount} files, "
                          f"actually deleted {count} files sized {format(deleted_size/MBFACTOR, '.2f')} MB"
                        )
        # just because I want to have asterisk in logs and i in output
        print(return_value.replace('[i]', '[*]'))
        return return_value.replace('\n', '<br><br>')
