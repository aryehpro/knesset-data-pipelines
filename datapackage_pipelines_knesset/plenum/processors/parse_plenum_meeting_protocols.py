import logging
import subprocess
import xml.etree.ElementTree

from knesset_data.protocols.plenum import PlenumProtocolFile
from knesset_data.protocols.exceptions import AntiwordException

from datapackage_pipelines_knesset.common import object_storage
from datapackage_pipelines_knesset.common.processors.base_processor import BaseProcessor


class ParsePlenumMeetingProtocolsProcessor(BaseProcessor):

    def __init__(self, *args, **kwargs):
        super(ParsePlenumMeetingProtocolsProcessor, self).__init__(*args, **kwargs)
        self._schema["fields"] = [
            {
                "name": "kns_plenum_session_id", "type": "integer",
                "description": "primary key from kns_plenumsession table"
            },
            {
                "name": "protocol_object_name", "type": "string",
                "description": "storage object name containing the downloaded protocol"
            },
            {
                "name": "protocol_extension", "type": "string",
                "description": "file extension of the downloaded protocol"
            },
            {
                "name": "text_object_name", "type": "string",
                "description": "storage object name containing the parsed protocol text"
            },
            {
                "name": "parts_object_name", "type": "string",
                "description": "storage object name containing the parsed protocol csv"
            }
        ]
        self._schema["primaryKey"] = ["kns_plenum_session_id"]
        self.s3 = object_storage.get_s3()

    def _process(self, datapackage, resources):
        return self._process_filter(datapackage, resources)

    def _filter_row(self, meeting_protocol, **kwargs):
        bucket = "plenum"
        protocol_object_name = meeting_protocol["protocol_object_name"]
        protocol_extension = meeting_protocol["protocol_extension"]
        base_object_name = "protocols/parsed/{}".format(meeting_protocol["kns_plenum_session_id"])
        parts_object_name = "{}.csv".format(base_object_name)
        text_object_name = "{}.txt".format(base_object_name)
        if not object_storage.exists(self.s3, bucket, parts_object_name, min_size=5):

            parse_args = (meeting_protocol["kns_plenum_session_id"], bucket, protocol_object_name,
                          parts_object_name, text_object_name)

            if protocol_extension == "doc":
                parse_res = self._parse_doc_protocol(*parse_args)
            elif protocol_extension == "rtf":
                parse_res = self._parse_rtf_protocol(*parse_args)
            elif protocol_extension == "docx":
                parse_res = None
            else:
                raise Exception("unknown extension: {}".format(protocol_extension))

            if not parse_res:
                # in case parsing failed - we remove all parsed files, to ensure re-parse next time
                object_storage.delete(self.s3, bucket, text_object_name)
                object_storage.delete(self.s3, bucket, parts_object_name)
                text_object_name = None
                parts_object_name = None
        yield {"kns_committee_id": meeting_protocol["kns_committee_id"],
               "kns_session_id": meeting_protocol["kns_session_id"],
               "protocol_object_name": protocol_object_name,
               "protocol_extension": protocol_extension,
               "text_object_name": text_object_name,
               "parts_object_name": parts_object_name}

    def _parse_rtf_protocol(self, committee_id, meeting_id, bucket, protocol_object_name, parts_object_name, text_object_name):
        # currently with the new API - we don't seem to get rtf files anymore
        # it looks like files which used to be rtf are actually doc
        # need to investigate further
        return False
        # rtf_extractor = os.environ.get("RTF_EXTRACTOR_BIN")
        # if rtf_extractor:
        #     with object_storage.temp_download(protocol_object_name) as protocol_filename:
        #         with tempfile.NamedTemporaryFile() as text_filename:
        #             cmd = rtf_extractor + ' ' + protocol_filename + ' ' + text_filename
        #             try:
        #                 subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
        #                 protocol_text = fs.read(text_filename)
        #                 with CommitteeMeetingProtocol.get_from_text(protocol_text) as protocol:
        #                     self._parse_protocol_parts(parts_filename, protocol)
        #             except subprocess.SubprocessError:
        #                 logging.exception("committee {} meeting {}: failed to parse rtf file, skipping".format(committee_id,
        #                                                                                                        meeting_id))
        #                 return False
        #             return True
        # else:
        #     logging.warning("missing RTF_EXTRACTOR_BIN environment variable, skipping rtf parsing")
        #     return False

    def _parse_doc_protocol(self, committee_id, meeting_id, bucket, protocol_object_name, parts_object_name, text_object_name):
        logging.info("parsing doc protocol {} --> {}, {}".format(protocol_object_name, parts_object_name, text_object_name))
        with object_storage.temp_download(self.s3, bucket, protocol_object_name) as protocol_filename:
            try:
                with CommitteeMeetingProtocol.get_from_filename(protocol_filename) as protocol:
                    object_storage.write(self.s3, bucket, text_object_name, protocol.text, public_bucket=True)
                    self._parse_protocol_parts(bucket, parts_object_name, protocol)
            except (
                    AntiwordException,  # see https://github.com/hasadna/knesset-data-pipelines/issues/15
                    subprocess.SubprocessError,
                    xml.etree.ElementTree.ParseError  # see https://github.com/hasadna/knesset-data-pipelines/issues/32
            ):
                logging.exception("committee {} meeting {}: failed to parse doc file, skipping".format(committee_id, meeting_id))
                return False
        return True

    def _parse_protocol_parts(self, bucket, parts_object_name, protocol):
        with object_storage.csv_writer(self.s3, bucket, parts_object_name, public_bucket=True) as csv_writer:
            csv_writer.writerow(["header", "body"])
            for part in protocol.parts:
                csv_writer.writerow([part.header, part.body])
            logging.info("parsed parts file -> {}".format(parts_object_name))

if __name__ == '__main__':
    ParseCommitteeMeetingProtocolsProcessor.main()
