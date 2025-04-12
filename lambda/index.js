const AWS = require('aws-sdk');
const { Client } = require('pg');

const secretsManager = new AWS.SecretsManager();

exports.handler = async (event) => {
	try {
		// Get secret ARN from env
		const secretArn = process.env.SECRET_ARN;

		// Fetch secret value
		const secretValue = await secretsManager.getSecretValue({ SecretId: secretArn }).promise();
		const secret = JSON.parse(secretValue.SecretString);

		const client = new Client({
			host: secret.host,
			user: secret.username,
			password: secret.password,
			port: secret.port,
			database: secret.dbname,
		});

		await client.connect();

		const res = await client.query('SELECT NOW() as time'); // Sample query

		await client.end();

		return {
			statusCode: 200,
			headers: {
				"Access-Control-Allow-Origin": "*",
				"Access-Control-Allow-Headers": "Content-Type",
				"Access-Control-Allow-Methods": "GET, POST, OPTIONS",
			},
			body: JSON.stringify({
				message: "Successfully connected to RDS!",
				timestamp: res.rows[0].time,
			}),
		};
	} catch (error) {
		console.error("Error:", error);
		return {
			statusCode: 500,
			headers: {
				"Access-Control-Allow-Origin": "*",
				"Access-Control-Allow-Headers": "Content-Type",
				"Access-Control-Allow-Methods": "GET, POST, OPTIONS",
			},
			body: JSON.stringify({
				error: "Failed to connect to database or fetch secret.",
				details: error.message,
			}),
		};
	}
};